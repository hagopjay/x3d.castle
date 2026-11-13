{ castle-render: render one X3D scene to a PNG with Castle Game Engine, every quality lever switchable
  from the command line. Built for measuring each lever on its own (see --list-levers).

  Build (separate manifest, castle-convert's own manifest is untouched):
    cd ../castle-render && castle-engine compile
  Run (headless, Mesa llvmpipe):
    LP_NUM_THREADS=2 xvfb-run -a ./castle-render SCENE.x3d OUT.png [levers]

  Writes OUT.png and OUT.png.json (options requested and applied, Castle version, GL renderer, seconds).
  Exit codes: 0 ok, 2 usage / unknown option / bad value, 3 lever not supported here, 4 input problem
  (scene, view json, ibl file), 5 rendering failed. A lever is never silently ignored.

  Quality levers and the Castle API each one drives (7.0-alpha.3 snapshot, read in the engine source):
    --shadows         X3D light field shadows=TRUE on every punctual light of the scene (shadow maps, receivers = all
                      shapes), set on the node tree before TCastleScene.Load. TCastleLight.Shadows is NOT this: it is
                      shadow VOLUMES, one light only. Shadow map size: TCastleScene.ShadowMapsDefaultSize.
    --shadow-sampling TCastleRenderOptions.ShadowSampling
    --ssao / --ssr    TCastleViewport.ScreenSpaceAmbientOcclusion / ScreenSpaceReflections (screen effects, run after
                      lighting, tone mapping and gamma)
    --tonemap         CastleRenderOptions.ToneMapping, a GLOBAL (all scenes), applied per fragment before gamma out
    --exposure        no engine lever exists (u_Exposure is commented out in tone_mapping.fs); done as a scene-wide
                      X3D Effect with PLUG_fragment_modify that multiplies rgb, which runs before tone mapping
    --colorspace      CastleRenderOptions.ColorSpace, a GLOBAL
    --shading         phong: RenderOptions.PhongShading. pbr: classic Material -> PhysicalMaterial on the node tree
                      (our mapping, not Castle's). gouraud: PhongShading=false. default: untouched
    --ibl             X3D EnvironmentLight node added to the scene (diffuse and specular cubemap)
    --msaa N          multisampled FBO (TGLRenderToTexture.MultiSampling), because Xvfb has no multisample visual
    --ssaa N          render N times larger FBO and downscale (not an engine lever, our addition)
    --aniso N         X3D TextureProperties.anisotropicDegree attached to every texture node on the node tree
}
program castle_render;
{$mode objfpc}{$H+}
{$ifdef MSWINDOWS} {$apptype CONSOLE} {$endif}

uses SysUtils, Classes, Types, StrUtils, Math, fpjson, jsonparser,
  CastleWindow, CastleViewport, CastleScene, CastleSceneCore, CastleTransform, CastleCameras,
  CastleVectors, CastleColors, CastleImages, CastleGLImages, CastleGLUtils, CastleGLVersion, CastleLog, CastleGL,
  CastleUtils, CastleRenderOptions, CastleRectangles, CastleApplicationProperties, CastleShapes,
  CastleUriUtils, CastleStringUtils, CastleTimeUtils, CastleFilesUtils,
  CastleUIControls, CastleProjection, X3DNodes, X3DFields, X3DLoad;

const
  GL_MAX_SAMPLES_ = $8D57;
  ToolName = 'castle-render';
  ToolVersion = '0.1';

type
  TRenderPath = (rpAuto, rpWindow, rpFbo);
  TShadingMode = (shDefault, shPhong, shGouraud, shPbr);
  THeadlightMode = (hmScene, hmOff, hmOn, hmLux);

  TLever = record
    Name, Values, Default_, Mechanism, Status: String;
  end;

const
  ToneMapNames: array [TToneMapping] of String = ('none', 'uncharted', 'hejl', 'aces');
  ColorSpaceNames: array [TColorSpace] of String = ('srgb', 'linear-when-physical-material (Castle default)', 'linear');
  Levers: array [0..25] of TLever = (
    (Name: '--size'; Values: 'N | WxH'; Default_: '512'; Mechanism: 'window size (Xvfb, no window manager: exact)'; Status: 'ok'),
    (Name: '--view-json'; Values: 'FILE (with --job-name NAME)'; Default_: 'scene Viewpoint'; Mechanism: 'TCastleCamera.SetView + Perspective.FieldOfView (faSmallest); jobs.json list or a bare {position,forward,up,fov}'; Status: 'ok'),
    (Name: '--clear'; Values: 'R,G,B (0..1)'; Default_: '0.1,0.1,0.1 (Castle default)'; Mechanism: 'TCastleViewport.BackgroundColor; hidden by a Background node in the scene'; Status: 'ok'),
    (Name: '--headlight'; Values: 'off | on | LUX | scene'; Default_: 'scene (NavigationInfo.headlight)'; Mechanism: 'Items.UseHeadlight + Items.HeadlightNode.Intensity (LUX = directional headlight intensity, same meaning as the rig job field)'; Status: 'ok'),
    (Name: '--shadows'; Values: 'flag'; Default_: 'off'; Mechanism: 'X3D light.shadows=TRUE on every punctual light before Load (shadow maps)'; Status: 'ok'),
    (Name: '--shadow-map-size'; Values: 'N'; Default_: '256 (Castle default)'; Mechanism: 'TCastleScene.ShadowMapsDefaultSize, read at Load'; Status: 'ok'),
    (Name: '--shadow-sampling'; Values: 'simple | pcf4 | pcf4bilinear | pcf16 | vsm'; Default_: 'pcf16 (Castle default)'; Mechanism: 'RenderOptions.ShadowSampling'; Status: 'ok'),
    (Name: '--ssao'; Values: 'flag'; Default_: 'off'; Mechanism: 'Viewport.ScreenSpaceAmbientOcclusion (screen effect, post tone map)'; Status: 'ok'),
    (Name: '--ssr'; Values: 'flag'; Default_: 'off'; Mechanism: 'Viewport.ScreenSpaceReflections (screen effect)'; Status: 'ok'),
    (Name: '--tonemap'; Values: 'none | aces | uncharted | hejl'; Default_: 'none'; Mechanism: 'CastleRenderOptions.ToneMapping (global)'; Status: 'ok'),
    (Name: '--exposure'; Values: 'F'; Default_: '1'; Mechanism: 'scene-wide Effect node, PLUG_fragment_modify rgb *= F, before tone mapping (no engine lever)'; Status: 'ok'),
    (Name: '--colorspace'; Values: 'default | srgb | linear'; Default_: 'default (linear for PhysicalMaterial only)'; Mechanism: 'CastleRenderOptions.ColorSpace (global)'; Status: 'ok'),
    (Name: '--shading'; Values: 'default | phong | gouraud | pbr'; Default_: 'default = phong (Castle 7.0-alpha.3 DefaultPhongShading is true)'; Mechanism: 'RenderOptions.PhongShading true/false, or classic Material -> PhysicalMaterial on the node tree (pbr)'; Status: 'ok'),
    (Name: '--ibl'; Values: 'none | FILE.dds|ktx | DIR (px nx py ny pz nz .png)'; Default_: 'none'; Mechanism: 'X3D EnvironmentLight node (see --ibl-intensity). Engine marks it unfinished'; Status: 'experimental'),
    (Name: '--ibl-intensity'; Values: 'F'; Default_: '1'; Mechanism: 'EnvironmentLight.intensity'; Status: 'experimental'),
    (Name: '--msaa'; Values: '1 | 2 | 4 | 8'; Default_: '1'; Mechanism: 'multisampled FBO (TGLRenderToTexture.MultiSampling); window multisample visuals do not exist under Xvfb'; Status: 'ok'),
    (Name: '--ssaa'; Values: 'N'; Default_: '1'; Mechanism: 'FBO N times larger, then N x N box average in display space (our addition)'; Status: 'ok'),
    (Name: '--aniso'; Values: 'N (1..GL max)'; Default_: '1 (none)'; Mechanism: 'TextureProperties.anisotropicDegree on every texture node'; Status: 'ok'),
    (Name: '--bump-mapping'; Values: 'none | basic | parallax | steep | steep-shadow'; Default_: 'basic'; Mechanism: 'RenderOptions.BumpMapping'; Status: 'ok'),
    (Name: '--min-filter'; Values: 'nearest | linear | mipmap-nearest | mipmap-linear (trilinear) | default'; Default_: 'default'; Mechanism: 'RenderOptions.MinificationFilter'; Status: 'ok'),
    (Name: '--max-lights'; Values: 'N'; Default_: 'Castle default'; Mechanism: 'RenderOptions.MaxLightsPerShape'; Status: 'ok'),
    (Name: '--path'; Values: 'auto | window | fbo'; Default_: 'auto (window unless msaa/ssaa)'; Mechanism: 'window back buffer SaveScreen, or offscreen FBO'; Status: 'ok'),
    (Name: '--time'; Values: 'SECONDS'; Default_: '0'; Mechanism: 'Scene.ResetTime(0) then Update(SECONDS)'; Status: 'ok'),
    (Name: '--no-update'; Values: 'flag'; Default_: 'off'; Mechanism: 'diagnostic: skip the Container.EventUpdate step. Shadow maps then are never generated; this reproduces castle-model-viewer --screenshot on scenes with shadows=TRUE'; Status: 'diagnostic'),
    (Name: '--verbose'; Values: 'flag'; Default_: 'off'; Mechanism: 'Castle log to stderr'; Status: 'ok'),
    (Name: '--list-levers'; Values: 'flag'; Default_: ''; Mechanism: 'print this table and exit 0'; Status: 'ok'));

var
  { options }
  SceneFile, OutFile: String;
  Size: TVector2Integer;
  ViewJson, JobName: String;
  ClearSet: Boolean;
  ClearColor: TVector3;
  HeadlightMode: THeadlightMode;
  HeadlightLux: Single;
  OptShadows, OptSsao, OptSsr, OptVerbose, OptNoUpdate: Boolean;
  ShadowMapSize: Cardinal;
  ShadowSamplingSet: Boolean;
  ShadowSampling: TShadowSampling;
  TonemapSet: Boolean;
  Tonemap: TToneMapping;
  TonemapName: String;
  ExposureSet: Boolean;
  Exposure: Single;
  ColorSpaceSet: Boolean;
  ColorSpaceVal: TColorSpace;
  ColorSpaceName: String;
  Shading: TShadingMode;
  IblArg: String;
  IblIntensity: Single;
  Msaa, Ssaa, Aniso: Cardinal;
  BumpSet: Boolean;
  BumpVal: TBumpMapping;
  BumpName: String;
  MinFilterSet: Boolean;
  MinFilter: TAutoMinificationFilter;
  MinFilterName: String;
  MaxLightsSet: Boolean;
  MaxLights: Cardinal;
  RenderPath: TRenderPath;
  SimTime: Double;
  Requested: TJSONObject;

  { results gathered while applying }
  Applied: TJSONObject;
  Warnings: TStringList;
  CntLightsShadows, CntLightsShadowsSkipped, CntTextureProps, CntMaterialsToPbr, CntLightsTotal, CntEffectsApplied: Integer;
  IblCubeMode: String;

procedure Die(const Code: Integer; const Msg: String);
var
  J: TJSONObject;
  SL: TStringList;
begin
  Writeln(ErrOutput, ToolName, ': ', Msg);
  { leave a machine-readable reason next to where the PNG would have been, so a driver never reads a stale pair }
  if OutFile <> '' then
  try
    J := TJSONObject.Create;
    J.Add('tool', ToolName + ' ' + ToolVersion);
    J.Add('error', Msg);
    J.Add('exit_code', Code);
    SL := TStringList.Create;
    try
      SL.Text := J.FormatJSON;
      SL.SaveToFile(ExpandFileName(OutFile) + '.json');
    finally SL.Free; end;
    J.Free;
  except
  end;
  Halt(Code);
end;

procedure PrintLevers(const AsJson: Boolean);
var
  I: Integer;
  A: TJSONArray;
  O: TJSONObject;
begin
  if AsJson then
  begin
    A := TJSONArray.Create;
    for I := Low(Levers) to High(Levers) do
    begin
      O := TJSONObject.Create;
      O.Add('lever', Levers[I].Name);
      O.Add('values', Levers[I].Values);
      O.Add('default', Levers[I].Default_);
      O.Add('mechanism', Levers[I].Mechanism);
      O.Add('status', Levers[I].Status);
      A.Add(O);
    end;
    Writeln(A.FormatJSON);
    A.Free;
  end else
  begin
    Writeln(ToolName, ' ', ToolVersion, '  levers (usage: ', ToolName, ' SCENE.x3d OUT.png [levers])');
    for I := Low(Levers) to High(Levers) do
    begin
      Writeln(Levers[I].Name, '  ', Levers[I].Values);
      Writeln('    default: ', Levers[I].Default_, '   status: ', Levers[I].Status);
      Writeln('    ', Levers[I].Mechanism);
    end;
  end;
end;

function ParseFloatStrict(const S, OptName: String): Single;
var
  D: Double;
begin
  if not TryStrToFloat(S, D, DefaultFormatSettings) then
    Die(2, 'bad number for ' + OptName + ': "' + S + '"');
  Result := D;
end;

function ParseCardStrict(const S, OptName: String): Cardinal;
var
  L: Int64;
begin
  if (not TryStrToInt64(S, L)) or (L < 1) or (L > 1000000) then
    Die(2, 'bad positive integer for ' + OptName + ': "' + S + '"');
  Result := Cardinal(L);
end;

procedure ParseArgs;
var
  I, NPos: Integer;
  Arg, Name, Val: String;
  HasVal: Boolean;
  P: Integer;
  Parts: Types.TStringDynArray;

  function NextVal: String;
  begin
    if HasVal then Exit(Val);
    Inc(I);
    if I > ParamCount then
      Die(2, 'option ' + Name + ' needs a value');
    Result := ParamStr(I);
  end;

  procedure Req(const K, V: String);
  begin
    Requested.Add(K, V);
  end;

begin
  { defaults }
  Size := Vector2Integer(512, 512);
  ClearSet := false;
  ClearColor := Vector3(0.1, 0.1, 0.1);
  HeadlightMode := hmScene;
  HeadlightLux := 1;
  ShadowMapSize := 0;
  Shading := shDefault;
  IblArg := 'none';
  IblIntensity := 1;
  Msaa := 1;
  Ssaa := 1;
  Aniso := 1;
  RenderPath := rpAuto;
  SimTime := 0;
  Exposure := 1;

  NPos := 0;
  I := 1;
  while I <= ParamCount do
  begin
    Arg := ParamStr(I);
    HasVal := false;
    Val := '';
    Name := Arg;
    if (Copy(Arg, 1, 2) = '--') then
    begin
      P := Pos('=', Arg);
      if P > 0 then
      begin
        Name := Copy(Arg, 1, P - 1);
        Val := Copy(Arg, P + 1, MaxInt);
        HasVal := true;
      end;
    end;

    if Name = '--list-levers' then
    begin
      PrintLevers(HasVal and (Val = 'json'));
      Halt(0);
    end
    else if Name = '--verbose' then begin OptVerbose := true; Req('verbose', 'true'); end
    else if Name = '--size' then
    begin
      Val := NextVal;
      Req('size', Val);
      Parts := StrUtils.SplitString(LowerCase(Val), 'x');
      if Length(Parts) = 1 then
        Size := Vector2Integer(ParseCardStrict(Parts[0], '--size'), ParseCardStrict(Parts[0], '--size'))
      else if Length(Parts) = 2 then
        Size := Vector2Integer(ParseCardStrict(Parts[0], '--size'), ParseCardStrict(Parts[1], '--size'))
      else Die(2, 'bad --size "' + Val + '", expected N or WxH');
    end
    else if Name = '--view-json' then begin ViewJson := NextVal; Req('view-json', ViewJson); end
    else if Name = '--job-name' then begin JobName := NextVal; Req('job-name', JobName); end
    else if Name = '--clear' then
    begin
      Val := NextVal;
      Req('clear', Val);
      Parts := StrUtils.SplitString(Val, ',');
      if Length(Parts) <> 3 then Die(2, 'bad --clear "' + Val + '", expected R,G,B');
      ClearColor := Vector3(ParseFloatStrict(Parts[0], '--clear'), ParseFloatStrict(Parts[1], '--clear'),
        ParseFloatStrict(Parts[2], '--clear'));
      ClearSet := true;
    end
    else if Name = '--headlight' then
    begin
      Val := NextVal;
      Req('headlight', Val);
      if Val = 'off' then HeadlightMode := hmOff
      else if Val = 'on' then HeadlightMode := hmOn
      else if Val = 'scene' then HeadlightMode := hmScene
      else
      begin
        HeadlightMode := hmLux;
        HeadlightLux := ParseFloatStrict(Val, '--headlight');
      end;
    end
    else if Name = '--no-update' then begin OptNoUpdate := true; Req('no-update', 'true'); end
    else if Name = '--shadows' then begin OptShadows := true; Req('shadows', 'true'); end
    else if Name = '--shadow-map-size' then
    begin
      Val := NextVal; Req('shadow-map-size', Val);
      ShadowMapSize := ParseCardStrict(Val, '--shadow-map-size');
    end
    else if Name = '--shadow-sampling' then
    begin
      Val := NextVal; Req('shadow-sampling', Val);
      ShadowSamplingSet := true;
      case LowerCase(Val) of
        'simple': ShadowSampling := ssSimple;
        'pcf4': ShadowSampling := ssPCF4;
        'pcf4bilinear': ShadowSampling := ssPCF4Bilinear;
        'pcf16': ShadowSampling := ssPCF16;
        'vsm': ShadowSampling := ssVarianceShadowMaps;
        else Die(2, 'bad --shadow-sampling "' + Val + '", expected simple|pcf4|pcf4bilinear|pcf16|vsm');
      end;
    end
    else if Name = '--ssao' then begin OptSsao := true; Req('ssao', 'true'); end
    else if Name = '--ssr' then begin OptSsr := true; Req('ssr', 'true'); end
    else if Name = '--tonemap' then
    begin
      Val := NextVal; Req('tonemap', Val);
      TonemapSet := true;
      TonemapName := LowerCase(Val);
      case TonemapName of
        'none': Tonemap := tmNone;
        'aces': Tonemap := tmACES;
        'uncharted': Tonemap := tmUncharted;
        'hejl', 'hejlrichard': begin Tonemap := tmHejlRichard; TonemapName := 'hejl'; end;
        else Die(3, 'tone map "' + Val + '" not offered by Castle 7.0-alpha.3; it has none, aces, uncharted, hejl only');
      end;
    end
    else if Name = '--exposure' then
    begin
      Val := NextVal; Req('exposure', Val);
      Exposure := ParseFloatStrict(Val, '--exposure');
      if Exposure <= 0 then Die(2, '--exposure must be > 0');
      ExposureSet := true;
    end
    else if Name = '--colorspace' then
    begin
      Val := NextVal; Req('colorspace', Val);
      ColorSpaceSet := true;
      ColorSpaceName := LowerCase(Val);
      case ColorSpaceName of
        'default': ColorSpaceVal := csLinearWhenPhysicalMaterial;
        'srgb': ColorSpaceVal := csSRGB;
        'linear': ColorSpaceVal := csLinear;
        else Die(2, 'bad --colorspace "' + Val + '", expected default|srgb|linear');
      end;
    end
    else if Name = '--shading' then
    begin
      Val := NextVal; Req('shading', Val);
      case LowerCase(Val) of
        'default': Shading := shDefault;
        'phong': Shading := shPhong;
        'gouraud': Shading := shGouraud;
        'pbr': Shading := shPbr;
        else Die(2, 'bad --shading "' + Val + '", expected default|phong|gouraud|pbr');
      end;
    end
    else if Name = '--ibl' then begin IblArg := NextVal; Req('ibl', IblArg); end
    else if Name = '--ibl-intensity' then
    begin
      Val := NextVal; Req('ibl-intensity', Val);
      IblIntensity := ParseFloatStrict(Val, '--ibl-intensity');
    end
    else if Name = '--msaa' then
    begin
      Val := NextVal; Req('msaa', Val);
      Msaa := ParseCardStrict(Val, '--msaa');
    end
    else if Name = '--ssaa' then
    begin
      Val := NextVal; Req('ssaa', Val);
      Ssaa := ParseCardStrict(Val, '--ssaa');
    end
    else if Name = '--aniso' then
    begin
      Val := NextVal; Req('aniso', Val);
      Aniso := ParseCardStrict(Val, '--aniso');
    end
    else if Name = '--bump-mapping' then
    begin
      Val := NextVal; Req('bump-mapping', Val);
      BumpSet := true;
      BumpName := LowerCase(Val);
      case BumpName of
        'none': BumpVal := bmNone;
        'basic': BumpVal := bmBasic;
        'parallax': BumpVal := bmParallax;
        'steep': BumpVal := bmSteepParallax;
        'steep-shadow': BumpVal := bmSteepParallaxShadowing;
        else Die(2, 'bad --bump-mapping "' + Val + '"');
      end;
    end
    else if Name = '--min-filter' then
    begin
      Val := NextVal; Req('min-filter', Val);
      MinFilterSet := true;
      MinFilterName := LowerCase(Val);
      case MinFilterName of
        'nearest': MinFilter := minNearest;
        'linear': MinFilter := minLinear;
        'mipmap-nearest': MinFilter := minLinearMipmapNearest;
        'mipmap-linear', 'trilinear': MinFilter := minLinearMipmapLinear;
        'default': MinFilter := minDefault;
        else Die(2, 'bad --min-filter "' + Val + '"');
      end;
    end
    else if Name = '--max-lights' then
    begin
      Val := NextVal; Req('max-lights', Val);
      MaxLightsSet := true;
      MaxLights := ParseCardStrict(Val, '--max-lights');
    end
    else if Name = '--path' then
    begin
      Val := NextVal; Req('path', Val);
      case LowerCase(Val) of
        'auto': RenderPath := rpAuto;
        'window': RenderPath := rpWindow;
        'fbo': RenderPath := rpFbo;
        else Die(2, 'bad --path "' + Val + '", expected auto|window|fbo');
      end;
    end
    else if Name = '--time' then
    begin
      Val := NextVal; Req('time', Val);
      SimTime := ParseFloatStrict(Val, '--time');
    end
    else if Copy(Arg, 1, 2) = '--' then
      Die(2, 'unknown option ' + Name + ' (see --list-levers)')
    else
    begin
      Inc(NPos);
      case NPos of
        1: SceneFile := Arg;
        2: OutFile := Arg;
        else Die(2, 'unexpected argument ' + Arg);
      end;
    end;
    Inc(I);
  end;
  if NPos <> 2 then
    Die(2, 'usage: ' + ToolName + ' SCENE.x3d OUT.png [levers]   (--list-levers to see them)');
  if (ViewJson <> '') and (JobName = '') and False then ;
  if (JobName <> '') and (ViewJson = '') then
    Die(2, '--job-name needs --view-json');
  if (Msaa > 1) and (Ssaa > 1) then
    Die(2, '--msaa and --ssaa together: pick one per run, so the lever is measured alone');
end;

{ ------------------------------------------------------------------------------------------------
  Node-tree edits, done on the X3D tree before TCastleScene.Load.
  Handlers are class procedures because EnumerateNodes wants a method pointer. }

type
  TNodeEdits = class
    class procedure LightShadows(Node: TX3DNode);
    class procedure CountLight(Node: TX3DNode);
    class procedure Texture2D(Node: TX3DNode);
    class procedure MaterialToPbr(Node: TX3DNode);
  end;

class procedure TNodeEdits.CountLight(Node: TX3DNode);
begin
  Inc(CntLightsTotal);
end;

class procedure TNodeEdits.LightShadows(Node: TX3DNode);
var
  L: TAbstractPunctualLightNode;
begin
  L := Node as TAbstractPunctualLightNode;
  { Only DirectionalLight and SpotLight override ProjectionMatrix (x3dnodes_standard_lighting.inc); a PointLight
    keeps the identity matrix of TAbstractPunctualLightNode, so shadows=TRUE on it builds a map nobody can sample
    sensibly (measured: garbage dark slabs in lights-after). Leave point lights alone and say so in the json. }
  if (L is TAbstractDirectionalLightNode) or (L is TSpotLightNode) or (L is TSpotLightNode_1) then
  begin
    L.FdShadows.Value := true;
    Inc(CntLightsShadows);
  end else
    Inc(CntLightsShadowsSkipped);
end;

class procedure TNodeEdits.Texture2D(Node: TX3DNode);
var
  Tex: TAbstractTexture2DNode;
  TP: TTexturePropertiesNode;
  OldTP: TTexturePropertiesNode;
begin
  Tex := Node as TAbstractTexture2DNode;
  OldTP := Tex.TextureProperties;
  TP := TTexturePropertiesNode.Create;
  TP.AnisotropicDegree := Aniso;
  { keep what the file said where it said something, otherwise X3D defaults for a texture node }
  if OldTP <> nil then
  begin
    TP.MinificationFilter := OldTP.MinificationFilter;
    TP.MagnificationFilter := OldTP.MagnificationFilter;
    TP.BoundaryModeS := OldTP.BoundaryModeS;
    TP.BoundaryModeT := OldTP.BoundaryModeT;
    TP.GenerateMipMaps := OldTP.GenerateMipMaps;
  end else
  begin
    TP.MinificationFilter := minDefault;
    TP.MagnificationFilter := magDefault;
    TP.BoundaryModeS := BoolRepeatToBoundaryMode[Tex.RepeatS];
    TP.BoundaryModeT := BoolRepeatToBoundaryMode[Tex.RepeatT];
  end;
  Tex.TextureProperties := TP;
  Inc(CntTextureProps);
end;

{ Castle's own gamma is a pure power 2.2 (tone_mapping.fs), so a classic display-space colour
  goes to the linear PhysicalMaterial slot with the same 2.2 power. }
function ToLin(const C: TVector3): TVector3;
begin
  Result := Vector3(Power(C.X, 2.2), Power(C.Y, 2.2), Power(C.Z, 2.2));
end;

class procedure TNodeEdits.MaterialToPbr(Node: TX3DNode);
var
  App: TAppearanceNode;
  Phong: TMaterialNode;
  Phys: TPhysicalMaterialNode;
begin
  App := Node as TAppearanceNode;
  if not (App.Material is TMaterialNode) then Exit;
  Phong := TMaterialNode(App.Material);
  Phys := TPhysicalMaterialNode.Create;
  Phys.BaseColor := ToLin(Phong.DiffuseColor);
  Phys.EmissiveColor := ToLin(Phong.EmissiveColor);
  Phys.Transparency := Phong.Transparency;
  Phys.Metallic := 0;
  if Phong.Shininess > 0 then
    Phys.Roughness := 1 - Sqrt(Phong.Shininess)
  else
    Phys.Roughness := 1;
  if Phong.DiffuseTexture <> nil then
    Phys.BaseTexture := Phong.DiffuseTexture;
  if Phong.NormalTexture <> nil then
    Phys.NormalTexture := Phong.NormalTexture;
  if Phong.EmissiveTexture <> nil then
    Phys.EmissiveTexture := Phong.EmissiveTexture;
  App.Material := Phys;
  Inc(CntMaterialsToPbr);
end;

function CubeFace(const Dir, Name: String): TImageTextureNode;
var
  Path: String;
begin
  Path := IncludeTrailingPathDelimiter(Dir) + Name + '.png';
  if not FileExists(Path) then
    Die(4, '--ibl directory ' + Dir + ' has no ' + Name + '.png');
  Result := TImageTextureNode.Create;
  Result.SetUrl([FilenameToUriSafe(Path)]);
end;

procedure AddIbl(const Root: TX3DRootNode);
var
  Light: TEnvironmentLightNode;
  Cube: TAbstractEnvironmentTextureNode;
  Composed: TComposedCubeMapTextureNode;
  Img: TImageCubeMapTextureNode;
begin
  if IblArg = 'none' then Exit;
  if DirectoryExists(IblArg) then
  begin
    { X3D face names: right +X, left -X, top +Y, bottom -Y, back +Z, front -Z (looking down the default -Z) }
    Composed := TComposedCubeMapTextureNode.Create;
    Composed.Right := CubeFace(IblArg, 'px');
    Composed.Left := CubeFace(IblArg, 'nx');
    Composed.Top := CubeFace(IblArg, 'py');
    Composed.Bottom := CubeFace(IblArg, 'ny');
    Composed.Back := CubeFace(IblArg, 'pz');
    Composed.Front := CubeFace(IblArg, 'nz');
    Cube := Composed;
    IblCubeMode := 'ComposedCubeMapTexture from 6 png';
  end else
  if FileExists(IblArg) and
     ((LowerCase(ExtractFileExt(IblArg)) = '.dds') or (LowerCase(ExtractFileExt(IblArg)) = '.ktx')) then
  begin
    Img := TImageCubeMapTextureNode.Create;
    Img.SetUrl([FilenameToUriSafe(ExpandFileName(IblArg))]);
    Cube := Img;
    IblCubeMode := 'ImageCubeMapTexture ' + ExtractFileExt(IblArg);
  end else
    Die(4, '--ibl "' + IblArg + '" is neither none, an existing .dds/.ktx cubemap, nor a directory with px nx py ny pz nz .png');

  Light := TEnvironmentLightNode.Create;
  Light.DiffuseTexture := Cube;
  Light.SpecularTexture := Cube;
  Light.Intensity := IblIntensity;
  Root.AddChildren(Light);
end;

function MakeExposureEffect: TEffectNode;
var
  Part: TEffectPartNode;
begin
  Result := TEffectNode.Create;
  Result.Language := slGLSL;
  Result.UniformMissing := umIgnore;
  Result.AddCustomField(TSFFloat.Create(Result, true, 'castle_render_exposure', Exposure));
  Part := TEffectPartNode.Create;
  Part.ShaderType := stFragment;
  Part.Contents :=
    'uniform float castle_render_exposure;' + LineEnding +
    'void PLUG_fragment_modify(inout vec4 fragment_color)' + LineEnding +
    '{' + LineEnding +
    '  fragment_color.rgb *= castle_render_exposure;' + LineEnding +
    '}' + LineEnding;
  Result.SetParts([Part]);
end;

{ ------------------------------------------------------------------------------------------------ }

type
  TWarnHandler = class
    class procedure OnCastleWarning(const Category, Message: String);
  end;

class procedure TWarnHandler.OnCastleWarning(const Category, Message: String);
begin
  Warnings.Add(Category + ': ' + Message);
  if OptVerbose then Writeln(ErrOutput, 'warning [', Category, ']: ', Message);
end;

function ReadFileText(const FN: String): String;
var
  SL: TStringList;
begin
  SL := TStringList.Create;
  try
    SL.LoadFromFile(FN);
    Result := SL.Text;
  finally SL.Free; end;
end;

type
  TView = record
    Pos, Dir, Up: TVector3;
    Fov: Single;
  end;

function LoadView(const FN, Job: String): TView;
var
  D: TJSONData;
  O, V: TJSONObject;
  A: TJSONArray;
  I: Integer;

  function Vec(const Name: String): TVector3;
  var
    Arr: TJSONArray;
  begin
    Arr := V.Find(Name, jtArray) as TJSONArray;
    if (Arr = nil) or (Arr.Count <> 3) then
      Die(4, 'view in ' + FN + ' has no 3-vector "' + Name + '"');
    Result := Vector3(Arr.Floats[0], Arr.Floats[1], Arr.Floats[2]);
  end;

begin
  if not FileExists(FN) then Die(4, 'view json not found: ' + FN);
  try
    D := GetJSON(ReadFileText(FN));
  except
    on E: Exception do Die(4, 'view json ' + FN + ' does not parse: ' + E.Message);
  end;
  V := nil;
  if D is TJSONArray then
  begin
    if Job = '' then Die(4, FN + ' is a job list, pass --job-name');
    A := TJSONArray(D);
    for I := 0 to A.Count - 1 do
    begin
      O := A.Objects[I];
      if O.Get('name', '') = Job then
      begin
        V := O.Find('view', jtObject) as TJSONObject;
        if V = nil then Die(4, 'job "' + Job + '" in ' + FN + ' has no view object');
        Break;
      end;
    end;
    if V = nil then Die(4, 'job "' + Job + '" not found in ' + FN);
  end else
  if D is TJSONObject then
  begin
    V := TJSONObject(D);
    if V.Find('view', jtObject) <> nil then V := V.Find('view', jtObject) as TJSONObject;
  end else
    Die(4, 'view json ' + FN + ' is neither a list nor an object');
  if V.Find('ortho') <> nil then
    Die(3, 'orthographic views are not wired in castle-render (the job has an "ortho" field)');
  Result.Pos := Vec('position');
  Result.Dir := Vec('forward');
  Result.Up := Vec('up');
  Result.Fov := V.Get('fov', 0.785398);
end;

{$warnings off} // MainScene / UseHeadlight / AutoCamera are deprecated but are exactly what castle-model-viewer's baseline follows
{ Average of N x N blocks of the (display-space, 8 bit) framebuffer, the same space an MSAA resolve averages in. }
function BoxDownscale(const Src: TRGBImage; const N: Cardinal): TRGBImage;
var
  X, Y, DX, DY: Integer;
  R, G, B, Cnt: Cardinal;
  P, Q: PVector3Byte;
begin
  Result := TRGBImage.Create(Src.Width div Integer(N), Src.Height div Integer(N));
  Cnt := N * N;
  for Y := 0 to Result.Height - 1 do
    for X := 0 to Result.Width - 1 do
    begin
      R := 0; G := 0; B := 0;
      for DY := 0 to Integer(N) - 1 do
        for DX := 0 to Integer(N) - 1 do
        begin
          P := Src.PixelPtr(X * Integer(N) + DX, Y * Integer(N) + DY);
          R := R + P^.X; G := G + P^.Y; B := B + P^.Z;
        end;
      Q := Result.PixelPtr(X, Y);
      Q^.X := (R + Cnt div 2) div Cnt;
      Q^.Y := (G + Cnt div 2) div Cnt;
      Q^.Z := (B + Cnt div 2) div Cnt;
    end;
end;

var
  Window: TCastleWindow;
  Viewport: TCastleViewport;
  Scene: TCastleScene;
  Root: TX3DRootNode;
  Eff: TEffectNode;
  Img, Small: TCastleImage;
  RT: TGLRenderToTexture;
  View: TView;
  ViewApplied: String;
  T0, TLoad, TRender, TEnd: QWord;
  ShapeCount, ShapesWithShadowMaps: Integer;
  EffW, EffH, UseFbo: Integer;
  PathUsed: String;
  J, Info: TJSONObject;
  Eff2: TJSONObject;
  MaxAniso: Single;
  SampleCount: Integer;
  Shape: TShape;
  JsonFile: TStringList;
  RenderedSize: TVector2Integer;
  WArr: TJSONArray;
  FboSamples, MaxSamples: Integer;
  K: Integer;
  RemoveMe: TRemoveType;
begin
  Requested := TJSONObject.Create;
  Applied := TJSONObject.Create;
  Warnings := TStringList.Create;
  ParseArgs;
  if OptVerbose then
    InitializeLog;
  ApplicationProperties.OnWarning.Add(@TWarnHandler(nil).OnCastleWarning);
  T0 := GetTickCount64;

  { never leave a stale result pair behind }
  if FileExists(OutFile) then DeleteFile(OutFile);
  if FileExists(OutFile + '.json') then DeleteFile(OutFile + '.json');
  if not FileExists(SceneFile) then Die(4, 'scene not found: ' + SceneFile);

  { 1. globals that are not per scene (CastleRenderOptions), set before any shader is built }
  if TonemapSet then ToneMapping := Tonemap;
  if ColorSpaceSet then ColorSpace := ColorSpaceVal;

  { 2. window = the GL context (no multisample visual is requested: Xvfb has none) }
  Window := TCastleWindow.Create(Application);
  Window.Width := Size.X;
  Window.Height := Size.Y;
  Window.Open;

  { 3. node tree edits, then the scene }
  try
    Root := LoadNode(SceneFile);
  except
    on E: Exception do Die(4, 'cannot load scene ' + SceneFile + ': ' + E.Message);
  end;
  Root.EnumerateNodes(TAbstractPunctualLightNode, @TNodeEdits(nil).CountLight, false);
  if OptShadows then
  begin
    Root.EnumerateNodes(TAbstractPunctualLightNode, @TNodeEdits(nil).LightShadows, false);
    if CntLightsShadows = 0 then
      Die(3, '--shadows: the scene has no DirectionalLight or SpotLight to switch shadows on (' +
        IntToStr(CntLightsShadowsSkipped) + ' PointLight(s) skipped: Castle 7.0-alpha.3 has no point-light shadow maps); ' +
        'add a Directional/Spot light in the X3D, refusing to write an unshadowed picture under a shadows label');
    if CntLightsShadowsSkipped > 0 then
      Warnings.Add('castle-render: ' + IntToStr(CntLightsShadowsSkipped) +
        ' PointLight(s) left without shadows: Castle 7.0-alpha.3 supports shadow maps for Directional and Spot lights only');
  end;
  if Aniso > 1 then
  begin
    MaxAniso := GLFeatures.MaxTextureMaxAnisotropy;
    if Aniso > MaxAniso then
      Die(3, '--aniso ' + IntToStr(Aniso) + ' exceeds GL_MAX_TEXTURE_MAX_ANISOTROPY ' + FloatToStr(MaxAniso));
    Root.EnumerateNodes(TAbstractTexture2DNode, @TNodeEdits(nil).Texture2D, false);
    if CntTextureProps = 0 then
      Warnings.Add('castle-render: --aniso requested but the scene has no 2D texture node, nothing to filter');
  end;
  if Shading = shPbr then
    Root.EnumerateNodes(TAppearanceNode, @TNodeEdits(nil).MaterialToPbr, false);
  if IblArg <> 'none' then AddIbl(Root);

  { The scene must already sit in a world (Viewport.Items) when it is loaded: shadow maps are set up inside Load and
    X3D lights ask the scene for its world transformation then. Loading first gives the warning
    "DirectionalLight(..) does not know the world transformation, results (like shadow maps) may be incorrect"
    and a black picture (measured, see notes). }
  Viewport := TCastleViewport.Create(Application);
  Scene := TCastleScene.Create(Application);
  Viewport.Items.Add(Scene);
  if ShadowMapSize > 0 then Scene.ShadowMapsDefaultSize := ShadowMapSize;
  Scene.Load(Root, true);
  Scene.ProcessEvents := true;
  Scene.ResetTime(0);

  case Shading of
    shPhong: Scene.RenderOptions.PhongShading := true;
    shGouraud: Scene.RenderOptions.PhongShading := false;
    else ;
  end;
  if ShadowSamplingSet then Scene.RenderOptions.ShadowSampling := ShadowSampling;
  if BumpSet then Scene.RenderOptions.BumpMapping := BumpVal;
  if MinFilterSet then Scene.RenderOptions.MinificationFilter := MinFilter;
  if MaxLightsSet then Scene.RenderOptions.MaxLightsPerShape := MaxLights;
  if ExposureSet then
  begin
    Eff := MakeExposureEffect;
    Scene.SetEffects([Eff]);
    CntEffectsApplied := 1;
  end;

  { 4. viewport }
  Viewport.FullSize := true;
  Viewport.BackgroundColor := Vector4(ClearColor, 1);
  Viewport.Items.MainScene := Scene;
  case HeadlightMode of
    hmScene: Viewport.Items.UseHeadlight := hlMainScene;
    hmOff: Viewport.Items.UseHeadlight := hlOff;
    hmOn: Viewport.Items.UseHeadlight := hlOn;
    hmLux:
      begin
        Viewport.Items.UseHeadlight := hlOn;
        Viewport.Items.HeadlightNode.Intensity := HeadlightLux;
      end;
  end;
  if ViewJson <> '' then
  begin
    View := LoadView(ViewJson, JobName);
    Viewport.AutoCamera := false;
    Viewport.Camera.ProjectionType := ptPerspective;
    Viewport.Camera.Perspective.FieldOfView := View.Fov;
    Viewport.Camera.Perspective.FieldOfViewAxis := faSmallest;
    Viewport.Camera.SetView(View.Pos, View.Dir, View.Up);
    ViewApplied := 'view-json ' + ViewJson + ' job ' + JobName;
  end else
  begin
    Viewport.AutoCamera := true;
    Viewport.AssignDefaultCamera;
    ViewApplied := 'scene bound Viewpoint (AssignDefaultCamera)';
  end;
  Window.Controls.InsertFront(Viewport);

  if OptSsao then
  begin
    if not Viewport.ScreenSpaceAmbientOcclusionAvailable then
      Die(3, '--ssao: Castle reports the SSAO screen effect is not available on this GL (' + GLVersion.Renderer + ')');
    Viewport.ScreenSpaceAmbientOcclusion := true;
  end;
  if OptSsr then
  begin
    if not Viewport.ScreenSpaceReflectionsAvailable then
      Die(3, '--ssr: Castle reports the SSR screen effect is not available on this GL (' + GLVersion.Renderer + ')');
    Viewport.ScreenSpaceReflections := true;
  end;

  if ClearSet and (Scene.BackgroundStack.Top <> nil) then
    Warnings.Add('castle-render: --clear given, but the scene has a Background node; the node wins, --clear only fills where there is none');
  if SimTime > 0 then
  begin
    RemoveMe := rtNone;
    Scene.Update(SimTime, RemoveMe);
  end;

  { Generated textures (shadow maps, RenderedTexture, cube maps) are only refreshed in TCastleScene.Update, never in
    Render. A program that renders without an event loop must run one Update itself, between BeforeRender (which
    prepares GL resources) and Render, or shadows=TRUE gives a picture where every fragment is in shadow.
    Measured here: skipping this made stilllife-x3d40 with shadows come out entirely black (mean 0.3/255). }
  Window.Container.EventBeforeRender;
  if not OptNoUpdate then
    Window.Container.EventUpdate;
  Window.Container.EventBeforeRender;

  TLoad := GetTickCount64;

  { 5. render }
  if (RenderPath = rpAuto) then
  begin
    if (Msaa > 1) or (Ssaa > 1) then RenderPath := rpFbo else RenderPath := rpWindow;
  end;
  if (RenderPath = rpWindow) and ((Msaa > 1) or (Ssaa > 1)) then
    Die(2, '--path window cannot do --msaa/--ssaa (Xvfb has no multisample visual)');

  try
    if RenderPath = rpWindow then
    begin
      PathUsed := 'window back buffer, Container.SaveScreen';
      Img := Window.Container.SaveScreen;
    end else
    begin
      PathUsed := 'offscreen FBO, msaa ' + IntToStr(Msaa) + ', ssaa ' + IntToStr(Ssaa);
      if (Msaa > 1) and (not GLFeatures.FBOMultiSampling) then
        Die(3, '--msaa: GL_ARB_framebuffer_object multisampling not available on ' + GLVersion.Renderer);
      if Msaa > 1 then
      begin
        MaxSamples := 0;
        glGetIntegerv(GL_MAX_SAMPLES_, @MaxSamples);
        if Integer(Msaa) > MaxSamples then
          Die(3, '--msaa ' + IntToStr(Msaa) + ' exceeds GL_MAX_SAMPLES ' + IntToStr(MaxSamples) + ' on ' + GLVersion.Renderer);
      end;
      EffW := Size.X * Ssaa;
      EffH := Size.Y * Ssaa;
      Viewport.FullSize := false;
      Viewport.Width := EffW;
      Viewport.Height := EffH;
      RT := TGLRenderToTexture.Create(EffW, EffH);
      try
        RT.Buffer := tbNone;
        RT.ColorBufferAlpha := false;
        RT.Stencil := true;
        RT.MultiSampling := Msaa;
        RT.GLContextOpen;
        RT.RenderBegin;
        try
          Window.Container.RenderControl(Viewport, Rectangle(0, 0, EffW, EffH));
          FboSamples := 0;
          glGetIntegerv(GL_SAMPLES, @FboSamples);
          if (Msaa > 1) and (FboSamples <> Integer(Msaa)) then
            Die(3, '--msaa ' + IntToStr(Msaa) + ': the driver rounded this to ' + IntToStr(FboSamples) +
              ' samples (' + GLVersion.Renderer + '); ask for ' + IntToStr(FboSamples) + ' so the label is true');
          Img := RT.SaveScreen(TRGBImage, Rectangle(0, 0, EffW, EffH));
        finally RT.RenderEnd; end;
      finally
        RT.Free;
      end;
      if Ssaa > 1 then
      begin
        Small := BoxDownscale(Img as TRGBImage, Ssaa);
        FreeAndNil(Img);
        Img := Small;
      end;
    end;
  except
    on E: Exception do Die(5, 'render failed: ' + E.ClassName + ': ' + E.Message);
  end;
  TRender := GetTickCount64;

  SaveImage(Img, FilenameToUriSafe(ExpandFileName(OutFile)));
  RenderedSize := Vector2Integer(Img.Width, Img.Height);
  FreeAndNil(Img);

  { 6. introspection: what Castle really did }
  ShapeCount := 0;
  ShapesWithShadowMaps := 0;
  for Shape in Scene.Shapes.TraverseList(false) do
  begin
    Inc(ShapeCount);
    if (Shape.InternalShadowMaps <> nil) and (Shape.InternalShadowMaps.Count > 0) then
      Inc(ShapesWithShadowMaps);
  end;
  if OptShadows and (ShapesWithShadowMaps = 0) then
    Warnings.Add('castle-render: --shadows set shadows=TRUE on ' + IntToStr(CntLightsShadows) +
      ' light(s) but no shape ended up with a shadow map receiver list');

  TEnd := GetTickCount64;

  Eff2 := TJSONObject.Create;
  Eff2.Add('render_path', PathUsed);
  Eff2.Add('size', TJSONArray.Create([RenderedSize.X, RenderedSize.Y]));
  Eff2.Add('view', ViewApplied);
    case HeadlightMode of
    hmScene: Eff2.Add('headlight', 'scene NavigationInfo.headlight');
    hmOff: Eff2.Add('headlight', 'off');
    hmOn: Eff2.Add('headlight', 'on, default headlight node');
    hmLux: Eff2.Add('headlight', 'on, intensity ' + FloatToStr(HeadlightLux));
  end;
  Eff2.Add('background_color_viewport', ClearColor.ToString);
  Eff2.Add('scene_has_background_node', Scene.BackgroundStack.Top <> nil);
  Eff2.Add('lights_in_scene', CntLightsTotal);
  Eff2.Add('lights_with_shadows_true', CntLightsShadows);
  Eff2.Add('point_lights_skipped_for_shadows', CntLightsShadowsSkipped);
  Eff2.Add('shapes', ShapeCount);
  Eff2.Add('shapes_receiving_shadow_maps', ShapesWithShadowMaps);
  Eff2.Add('shadow_map_size_default', Integer(Scene.ShadowMapsDefaultSize));
  Eff2.Add('shadow_sampling', ShadowSamplingNames[Scene.RenderOptions.ShadowSampling]);
  Eff2.Add('phong_shading_render_option', Scene.RenderOptions.PhongShading);
  Eff2.Add('materials_converted_to_pbr', CntMaterialsToPbr);
  Eff2.Add('texture_nodes_with_anisotropy', CntTextureProps);
  Eff2.Add('aniso_degree', Integer(Aniso));
  Eff2.Add('ssao', Viewport.ScreenSpaceAmbientOcclusion);
  Eff2.Add('ssr', Viewport.ScreenSpaceReflections);
  Eff2.Add('tonemap_global', ToneMapNames[ToneMapping]);
  Eff2.Add('colorspace_global', ColorSpaceNames[ColorSpace]);
  Eff2.Add('update_step_run', not OptNoUpdate);
  Eff2.Add('exposure_effects', CntEffectsApplied);
  Eff2.Add('exposure', Exposure);
  Eff2.Add('ibl', IblArg);
  Eff2.Add('ibl_mode', IblCubeMode);
  Eff2.Add('bump_mapping', BumpMappingNames[Scene.RenderOptions.BumpMapping]);
  Eff2.Add('gl_current_multisampling_of_window', Integer(GLFeatures.CurrentMultiSampling));
  if RenderPath = rpFbo then Eff2.Add('fbo_gl_samples', FboSamples);
  Eff2.Add('gl_fbo_multisampling', GLFeatures.FBOMultiSampling);
  Eff2.Add('gl_max_anisotropy', Double(GLFeatures.MaxTextureMaxAnisotropy));

  J := TJSONObject.Create;
  J.Add('tool', ToolName + ' ' + ToolVersion);
  J.Add('castle_version', CastleEngineVersion);
  J.Add('fpc', {$I %FPCVERSION%});
  J.Add('gl_renderer', GLVersion.Renderer);
  J.Add('gl_vendor', GLVersion.Vendor);
  J.Add('gl_version', GLVersion.VendorVersion);
  J.Add('scene', ExpandFileName(SceneFile));
  J.Add('out', ExpandFileName(OutFile));
  J.Add('options_requested', Requested);
  J.Add('options_applied', Eff2);
  Info := TJSONObject.Create;
  Info.Add('load_and_setup', (TLoad - T0) / 1000);
  Info.Add('render_and_save', (TRender - TLoad) / 1000);
  Info.Add('total', (TEnd - T0) / 1000);
  J.Add('seconds', Info);
  WArr := TJSONArray.Create;
  for K := 0 to Warnings.Count - 1 do WArr.Add(Warnings[K]);
  J.Add('warnings', WArr);

  JsonFile := TStringList.Create;
  try
    JsonFile.Text := J.FormatJSON;
    JsonFile.SaveToFile(ExpandFileName(OutFile) + '.json');
  finally JsonFile.Free; end;
  J.Free;
  Writeln(ToolName, ': wrote ', OutFile, ' (', RenderedSize.X, 'x', RenderedSize.Y, ', ',
    FormatFloat('0.00', (TRender - T0) / 1000), ' s, ', PathUsed, ')');
end.
