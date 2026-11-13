{ X3DCastleExport: X3D -> glTF 2.0 exporter built on Castle Game Engine's own
  render-ready geometry (TShape.GeometryArrays), the same arrays Castle sends to the GPU.

  Why this exists. Castle's stock glTF writer (X3DLoadInternalGltf, SaveGLTF) walks the
  node graph by hand and keeps only geometry, material factors and Transform T/R/S.
  This unit walks Castle's *shape tree* instead, so everything Castle resolves for
  rendering is resolved for export too: Inline content, Switch.whichChoice, Transform
  center / scaleOrientation, per-corner normals (creaseAngle), texture-coordinate
  generation, vertex colours, proxies (Box, Sphere, Extrusion, Text, ...), lines, points.
  Each Shape becomes one glTF node (world matrix on the node) with one mesh primitive.

  Not covered: animation, skinning, shaders, Billboard, GaussianSplats (Castle has no node),
  Background / Fog, cube and 3D textures, texture coordinate set > 0.

  Licence note: this file is original code for this project; it links against Castle Game
  Engine (LGPL with static linking exception) and PasGLTF (zlib licence). }
unit X3DCastleExport;

{$mode objfpc}{$H+}

interface

type
  TColourSpaceMode = (csAsIs, csSrgb);

  TExportOptions = record
    Camera: Boolean;        // write the bound (or X3D default) Viewpoint as a glTF camera
    Lights: Boolean;        // write X3D lights as KHR_lights_punctual
    Headlight: Boolean;     // write the X3D headlight as a directional light under the camera
    Textures: Boolean;      // embed image textures
    PhongSpecular: Boolean; // classic Material specular via KHR_materials_specular (black specularColor -> specularFactor 0)
    SpecularMaxF0: Single;  // upper bound for the F0 the extension is asked for (see docs/exporter.md)
    TextQuads: Boolean;     // keep Text as Castle's untextured glyph-cell quads (off by default: they read as solid bars)
    ColourSpace: TColourSpaceMode; // csSrgb: classic (display-space) colours to linear
    LightScale: Single;     // multiplies X3D light intensity; 0 = auto (pi when the lit shapes are mostly classic Material, else 1)
    Verbose: Boolean;
  end;

function DefaultExportOptions: TExportOptions;

{ Export InUrl to OutFile (.glb or .gltf). Also writes OutFile + '.export.json' with counts and
  warnings. Returns True when a file was written. }
function ExportScene(const InUrl, OutFile: String; const Opt: TExportOptions): Boolean;

implementation

uses SysUtils, Classes, Math, TypInfo, Generics.Collections,
  CastlePasGLTF, CastlePasJSON,
  CastleUtils, CastleVectors, CastleLog, CastleClassUtils, CastleStringUtils,
  CastleDownload, CastleUriUtils, CastleImages, CastleRenderOptions,
  CastleSceneCore, CastleShapes, X3DNodes, X3DFields,
  CastleInternalGeometryArrays, CastleInternalGLUtils;

function DefaultExportOptions: TExportOptions;
begin
  Result.Camera := true;
  Result.Lights := true;
  Result.Headlight := true;
  Result.Textures := true;
  Result.PhongSpecular := true;
  Result.SpecularMaxF0 := 0.5;
  Result.TextQuads := false;
  Result.ColourSpace := csSrgb;
  Result.LightScale := 0; { 0 = auto }
  Result.Verbose := false;
end;

type
  TSingleArray = array of Single;
  TCardArray = array of UInt32;
  TStrIntMap = specialize TDictionary<String, Integer>;
  TLitSurface = record
    Centre: TVector3;
    Half: Single;
  end;

  TExporter = class
  public
    Opt: TExportOptions;
    Doc: TPasGLTF.TDocument;
    Buf: TPasGLTF.TBuffer;
    GScene: TPasGLTF.TScene;
    MatCache: TStrIntMap;
    TexCache: TStrIntMap;
    ImgCache: TStrIntMap;
    LightsArr: TPasJSONItemArray;
    Warnings: TStringList;
    Scene: TCastleSceneCore;
    CameraNode: Integer;
    { stats }
    NShapes, NShapesSkipped, NTextSkipped, NVerts, NTris, NLineSegs, NPoints: Integer;
    NMaterials, NTextures, NImages, NLights, NCameras: Integer;
    NVertexColourShapes, NTexturedShapes, NUnlitMaterials, NBaked: Integer;
    ImageBytes: Int64;
    HeadlightWritten: Boolean;
    NLitClassic, NLitPhysical: Integer;
    EffScale: Single;       // manual --light-scale, or 1
    AutoUnits: Boolean;     // match what X3D browsers draw: see PrepareLightUnits
    ClassicScene: Boolean;
    Typical: Single;        // median albedo of the classic Materials
    Surfaces: array of TLitSurface;
    Albedos: array of Single;
    CamPos, CamDir, CamUp: TVector3;
    CamFov: Single;
    CamFromViewpoint: Boolean;

    constructor Create;
    destructor Destroy; override;
    procedure Log(const S: String);
    procedure Warn(const S: String);
    procedure Align4;
    function AddView(const Data; const Size: Int64; const Target: TPasGLTF.TBufferView.TTargetType): Integer;
    function AddFloatAccessor(const A: TSingleArray; const Comps: Integer; const MinMax: Boolean): Integer;
    function AddIndexAccessor(const A: TCardArray): Integer;
    function Lin(const C: Single): Single;
    function GetImage(const T2: TAbstractTexture2DNode): Integer;
    function GetTexture(const Tex: TAbstractTextureNode): Integer;
    procedure SetTexInfo(const Info: TPasGLTF.TMaterial.TTexture; const TexIdx: Integer;
      const App: TAppearanceNode);
    function GetMaterial(const Shape: TShape; const G: TGeometryArrays; const Lines: Boolean): Integer;
    procedure ExportShape(const Shape: TShape; const Index: Integer);
    procedure ResolveCamera;
    procedure UpdateLods(const T: TShapeTree);
    procedure ExportCamera;
    procedure ExportLights;
    procedure PrepareLightUnits;
    function Level(const X: Single): Single;
    function ReferenceDistance(const Origin: TVector3; const Radius: Single;
      const HasAxis: Boolean; const Axis: TVector3; const CutOff: Single): Single;
    function AddLightNode(const LightIdx: Integer; const M: TPasGLTF.TMatrix4x4;
      const Name: String; const Parent: Integer): Integer;
    function Run(const InUrl, OutFile: String): Boolean;
    function JsonReport(const InUrl, OutFile: String): String;
  end;

constructor TExporter.Create;
begin
  inherited Create;
  MatCache := TStrIntMap.Create;
  TexCache := TStrIntMap.Create;
  ImgCache := TStrIntMap.Create;
  Warnings := TStringList.Create;
  CameraNode := -1;
end;

destructor TExporter.Destroy;
begin
  FreeAndNil(MatCache);
  FreeAndNil(TexCache);
  FreeAndNil(ImgCache);
  FreeAndNil(Warnings);
  inherited;
end;

procedure TExporter.Log(const S: String);
begin
  if Opt.Verbose then
    Writeln(ErrOutput, '[export] ', S);
end;

procedure TExporter.Warn(const S: String);
begin
  if Warnings.IndexOf(S) < 0 then
  begin
    Warnings.Add(S);
    Writeln(ErrOutput, '[export] WARNING: ', S);
  end;
end;

function V4G(const V: TVector4): TPasGLTF.TVector4;
begin
  Move(V, Result, SizeOf(Result));
end;

function V3G(const V: TVector3): TPasGLTF.TVector3;
begin
  Move(V, Result, SizeOf(Result));
end;

{ Matrix helpers ------------------------------------------------------------ }

function MatToGltf(const M: TMatrix4): TPasGLTF.TMatrix4x4;
var
  C, R: Integer;
begin
  for C := 0 to 3 do
    for R := 0 to 3 do
      Result[C * 4 + R] := M.Columns[C].Data[R];
end;

function IsIdentityGltf(const M: TPasGLTF.TMatrix4x4): Boolean;
var
  I: Integer;
  E: Single;
begin
  Result := true;
  for I := 0 to 15 do
  begin
    if I mod 5 = 0 then E := 1 else E := 0;
    if Abs(M[I] - E) > 1e-6 then
      Exit(false);
  end;
end;

{ Matrix with the glTF camera/light convention: looks down local -Z, up is +Y. }
function BasisMatrix(const Pos, Dir, Up: TVector3): TPasGLTF.TMatrix4x4;
var
  X, Y, Z, U: TVector3;
  Cr: TVector3;
begin
  Z := (-Dir).Normalize;
  U := Up;
  Cr := TVector3.CrossProduct(U, Z);
  if Cr.Length < 1e-4 then
  begin
    U := Vector3(1, 0, 0);
    Cr := TVector3.CrossProduct(U, Z);
  end;
  X := Cr.Normalize;
  Y := TVector3.CrossProduct(Z, X);
  Result[0] := X.X;  Result[1] := X.Y;  Result[2] := X.Z;  Result[3] := 0;
  Result[4] := Y.X;  Result[5] := Y.Y;  Result[6] := Y.Z;  Result[7] := 0;
  Result[8] := Z.X;  Result[9] := Z.Y;  Result[10] := Z.Z; Result[11] := 0;
  Result[12] := Pos.X; Result[13] := Pos.Y; Result[14] := Pos.Z; Result[15] := 1;
end;

{ Buffer building ------------------------------------------------------------ }

procedure TExporter.Align4;
var
  Z: Byte;
begin
  Z := 0;
  while (Buf.Data.Size mod 4) <> 0 do
    Buf.Data.WriteBuffer(Z, 1);
end;

function TExporter.AddView(const Data; const Size: Int64;
  const Target: TPasGLTF.TBufferView.TTargetType): Integer;
var
  BV: TPasGLTF.TBufferView;
begin
  Align4;
  BV := TPasGLTF.TBufferView.Create(Doc);
  BV.Buffer := 0;
  BV.ByteOffset := Buf.Data.Size;
  BV.ByteLength := Size;
  BV.Target := Target;
  Buf.Data.WriteBuffer(Data, Size);
  Doc.BufferViews.Add(BV);
  Result := Doc.BufferViews.Count - 1;
end;

function TExporter.AddFloatAccessor(const A: TSingleArray; const Comps: Integer;
  const MinMax: Boolean): Integer;
var
  Acc: TPasGLTF.TAccessor;
  N, I, C: Integer;
  Mn, Mx: array [0..3] of Single;
begin
  N := Length(A) div Comps;
  if N = 0 then
    Exit(-1);
  Acc := TPasGLTF.TAccessor.Create(Doc);
  Acc.BufferView := AddView(A[0], Length(A) * SizeOf(Single), TPasGLTF.TBufferView.TTargetType.ArrayBuffer);
  Acc.ByteOffset := 0;
  Acc.ComponentType := TPasGLTF.TAccessor.TComponentType.Float;
  case Comps of
    1: Acc.Type_ := TPasGLTF.TAccessor.TType.Scalar;
    2: Acc.Type_ := TPasGLTF.TAccessor.TType.Vec2;
    3: Acc.Type_ := TPasGLTF.TAccessor.TType.Vec3;
    4: Acc.Type_ := TPasGLTF.TAccessor.TType.Vec4;
  end;
  Acc.Count := N;
  if MinMax then
  begin
    for C := 0 to Comps - 1 do
    begin
      Mn[C] := A[C];
      Mx[C] := A[C];
    end;
    for I := 1 to N - 1 do
      for C := 0 to Comps - 1 do
      begin
        if A[I * Comps + C] < Mn[C] then Mn[C] := A[I * Comps + C];
        if A[I * Comps + C] > Mx[C] then Mx[C] := A[I * Comps + C];
      end;
    case Comps of
      2: begin Acc.MinArray.Add([Mn[0], Mn[1]]); Acc.MaxArray.Add([Mx[0], Mx[1]]); end;
      3: begin Acc.MinArray.Add([Mn[0], Mn[1], Mn[2]]); Acc.MaxArray.Add([Mx[0], Mx[1], Mx[2]]); end;
      4: begin Acc.MinArray.Add([Mn[0], Mn[1], Mn[2], Mn[3]]); Acc.MaxArray.Add([Mx[0], Mx[1], Mx[2], Mx[3]]); end;
    end;
  end;
  Doc.Accessors.Add(Acc);
  Result := Doc.Accessors.Count - 1;
end;

function TExporter.AddIndexAccessor(const A: TCardArray): Integer;
var
  Acc: TPasGLTF.TAccessor;
  I: Integer;
  MaxIdx, MinIdx: UInt32;
  Short: array of UInt16;
begin
  if Length(A) = 0 then
    Exit(-1);
  MinIdx := A[0];
  MaxIdx := A[0];
  for I := 1 to High(A) do
  begin
    if A[I] < MinIdx then MinIdx := A[I];
    if A[I] > MaxIdx then MaxIdx := A[I];
  end;
  Acc := TPasGLTF.TAccessor.Create(Doc);
  Acc.ByteOffset := 0;
  if MaxIdx < 65535 then
  begin
    SetLength(Short, Length(A));
    for I := 0 to High(A) do
      Short[I] := A[I];
    Acc.BufferView := AddView(Short[0], Length(Short) * SizeOf(UInt16),
      TPasGLTF.TBufferView.TTargetType.ElementArrayBuffer);
    Acc.ComponentType := TPasGLTF.TAccessor.TComponentType.UnsignedShort;
  end else
  begin
    Acc.BufferView := AddView(A[0], Length(A) * SizeOf(UInt32),
      TPasGLTF.TBufferView.TTargetType.ElementArrayBuffer);
    Acc.ComponentType := TPasGLTF.TAccessor.TComponentType.UnsignedInt;
  end;
  Acc.Type_ := TPasGLTF.TAccessor.TType.Scalar;
  Acc.Count := Length(A);
  Acc.MinArray.Add(MinIdx);
  Acc.MaxArray.Add(MaxIdx);
  Doc.Accessors.Add(Acc);
  Result := Doc.Accessors.Count - 1;
end;

{ Colour --------------------------------------------------------------------- }

{ Classic X3D colours are display-space; glTF factors are linear. With csSrgb we convert
  display-space to linear so a viewer's sRGB encode lands back on the authored value. }
function TExporter.Lin(const C: Single): Single;
begin
  if Opt.ColourSpace = csAsIs then
    Exit(C);
  if C <= 0.04045 then
    Result := C / 12.92
  else
    Result := Power((C + 0.055) / 1.055, 2.4);
end;

{ Textures ------------------------------------------------------------------- }

function PtrKey(const P: Pointer): String;
begin
  Result := IntToHex(PtrUInt(P), 16);
end;

function TExporter.GetImage(const T2: TAbstractTexture2DNode): Integer;
var
  Mem: TMemoryStream;
  Url, Mime: String;
  Src: TStream;
  Img: TPasGLTF.TImage;
begin
  if ImgCache.TryGetValue(PtrKey(T2), Result) then
    Exit;
  Result := -1;
  Mem := TMemoryStream.Create;
  try
    Url := T2.TextureUsedFullUrl;
    Mime := '';
    if Url <> '' then
      Mime := UriMimeType(Url);
    try
      if (Url <> '') and ((Mime = 'image/png') or (Mime = 'image/jpeg')) then
      begin
        Src := Download(Url, [soForceMemoryStream]);
        try
          Mem.CopyFrom(Src, 0);
        finally FreeAndNil(Src) end;
      end else
      begin
        SaveImage(T2.TextureImage, 'image/png', Mem);
        Mime := 'image/png';
      end;
    except
      on E: Exception do
      begin
        Warn(Format('texture image not embedded (%s %s): %s', [T2.NiceName, Url, E.Message]));
        Exit;
      end;
    end;
    if Mem.Size = 0 then
      Exit;
    Img := TPasGLTF.TImage.Create(Doc);
    Img.Name := T2.X3DName;
    Img.MimeType := Mime;
    Img.BufferView := AddView(Mem.Memory^, Mem.Size, TPasGLTF.TBufferView.TTargetType.None);
    Doc.Images.Add(Img);
    Result := Doc.Images.Count - 1;
    Inc(NImages);
    ImageBytes := ImageBytes + Mem.Size;
    Log(Format('image %d: %s %s, %d bytes', [Result, Mime, Url, Mem.Size]));
  finally FreeAndNil(Mem) end;
  ImgCache.Add(PtrKey(T2), Result);
end;

function TExporter.GetTexture(const Tex: TAbstractTextureNode): Integer;
var
  T: TAbstractTextureNode;
  T2: TAbstractTexture2DNode;
  Key: String;
  Sm: TPasGLTF.TSampler;
  Tx: TPasGLTF.TTexture;
  Img: Integer;

  function Wrap(const R: Boolean): TPasGLTF.TSampler.TWrappingMode;
  begin
    if R then
      Result := TPasGLTF.TSampler.TWrappingMode.Repeat_
    else
      Result := TPasGLTF.TSampler.TWrappingMode.ClampToEdge;
  end;

begin
  Result := -1;
  if (not Opt.Textures) or (Tex = nil) then
    Exit;
  T := Tex;
  if (T is TMultiTextureNode) and (TMultiTextureNode(T).FdTexture.Count > 0) and
     (TMultiTextureNode(T).FdTexture[0] is TAbstractTextureNode) then
    T := TAbstractTextureNode(TMultiTextureNode(T).FdTexture[0]);
  if not (T is TAbstractTexture2DNode) then
  begin
    Warn('texture type not exported: ' + T.NiceName);
    Exit;
  end;
  T2 := TAbstractTexture2DNode(T);
  Key := PtrKey(T2) + '|' + BoolToStr(T2.RepeatS, '1', '0') + BoolToStr(T2.RepeatT, '1', '0');
  if TexCache.TryGetValue(Key, Result) then
    Exit;
  Result := -1;
  if not T2.IsTextureImage then
  begin
    Warn('texture failed to load: ' + T2.NiceName);
    Exit;
  end;
  Img := GetImage(T2);
  if Img < 0 then
    Exit;
  Sm := TPasGLTF.TSampler.Create(Doc);
  Sm.WrapS := Wrap(T2.RepeatS);
  Sm.WrapT := Wrap(T2.RepeatT);
  Sm.MagFilter := TPasGLTF.TSampler.TMagFilter.Linear;
  Sm.MinFilter := TPasGLTF.TSampler.TMinFilter.LinearMipMapLinear;
  Doc.Samplers.Add(Sm);
  Tx := TPasGLTF.TTexture.Create(Doc);
  Tx.Source := Img;
  Tx.Sampler := Doc.Samplers.Count - 1;
  Doc.Textures.Add(Tx);
  Result := Doc.Textures.Count - 1;
  Inc(NTextures);
  TexCache.Add(Key, Result);
end;

{ Fill a glTF textureInfo. X3D TextureTransform becomes KHR_texture_transform: build the X3D
  3x3 (T * C * R * S * C^-1), conjugate by the V flip, read offset / rotation / scale. }
procedure TExporter.SetTexInfo(const Info: TPasGLTF.TMaterial.TTexture; const TexIdx: Integer;
  const App: TAppearanceNode);
var
  TT: TTextureTransformNode;
  Cs, Sn, Sx, Sy, Cx, Cy, Tx, Ty: Double;
  { 2D affine: [a b; c d] and translation (e, f) in X3D space }
  A, B, C, D, E, F: Double;
  A2, B2, C2, D2, E2, F2: Double;
  Ext: TPasJSONItemObject;
  Off, Scl: TPasJSONItemArray;
  Rot, S0, S1: Double;
begin
  Info.Index := TexIdx;
  Info.TexCoord := 0;
  if (App = nil) or not (App.TextureTransform is TTextureTransformNode) then
    Exit;
  TT := TTextureTransformNode(App.TextureTransform);
  { X3D: tc' = T * C * R * S * C^-1 * tc }
  Cs := Cos(TT.Rotation);
  Sn := Sin(TT.Rotation);
  Sx := TT.Scale.X;
  Sy := TT.Scale.Y;
  Cx := TT.Center.X;
  Cy := TT.Center.Y;
  Tx := TT.Translation.X;
  Ty := TT.Translation.Y;
  { linear part R*S }
  A := Cs * Sx;  B := -Sn * Sy;
  C := Sn * Sx;  D := Cs * Sy;
  { translation: T + C - (R*S)*C }
  E := Tx + Cx - (A * Cx + B * Cy);
  F := Ty + Cy - (C * Cx + D * Cy);
  { conjugate by flip (s,t) -> (s,1-t): A'=A, B'=-B, C'=-C, D'=D, E'=E+B, F'=1-F-D }
  A2 := A;  B2 := -B;
  C2 := -C; D2 := D;
  E2 := E + B;
  F2 := 1 - F - D;
  { KHR: uv' = T * R(theta) * S * uv with R = [cos sin; -sin cos] }
  S0 := Sqrt(A2 * A2 + C2 * C2);
  S1 := Sqrt(B2 * B2 + D2 * D2);
  if (A2 * D2 - B2 * C2) < 0 then
    S1 := -S1;
  Rot := ArcTan2(-C2, A2);
  Ext := TPasJSONItemObject.Create;
  Off := TPasJSONItemArray.Create;
  Off.Add(TPasJSONItemNumber.Create(E2));
  Off.Add(TPasJSONItemNumber.Create(F2));
  Scl := TPasJSONItemArray.Create;
  Scl.Add(TPasJSONItemNumber.Create(S0));
  Scl.Add(TPasJSONItemNumber.Create(S1));
  Ext.Add('offset', Off);
  Ext.Add('rotation', TPasJSONItemNumber.Create(Rot));
  Ext.Add('scale', Scl);
  Info.Extensions.Add('KHR_texture_transform', Ext);
  if Doc.ExtensionsUsed.IndexOf('KHR_texture_transform') < 0 then
    Doc.ExtensionsUsed.Add('KHR_texture_transform');
end;

{ Materials ------------------------------------------------------------------ }

function TExporter.GetMaterial(const Shape: TShape; const G: TGeometryArrays;
  const Lines: Boolean): Integer;
var
  SN: TAbstractShapeNode;
  App: TAppearanceNode;
  Mat: TAbstractMaterialNode;
  GM: TPasGLTF.TMaterial;
  Key: String;
  DoubleSided, Unlit: Boolean;
  Base: TVector4;
  BaseTex, T: Integer;
  AC: TAlphaChannel;
  Phys: TPhysicalMaterialNode;
  Phong: TMaterialNode;
  Em: TVector3;
  Spec: TVector3;
  Roughness: Single;
  AlphaMode: TPasGLTF.TMaterial.TAlphaMode;
  MainTex: TAbstractTextureNode;
  Ext: TPasJSONItemObject;
  SpecArr: TPasJSONItemArray;

  procedure UseExt(const Name: String);
  begin
    if Doc.ExtensionsUsed.IndexOf(Name) < 0 then
      Doc.ExtensionsUsed.Add(Name);
  end;

begin
  SN := Shape.OriginalState.ShapeNode;
  App := nil;
  if SN <> nil then
    App := SN.Appearance;
  Mat := nil;
  if App <> nil then
    Mat := App.Material;
  DoubleSided := not G.CullFace;
  AC := Shape.AlphaChannel;

  Key := PtrKey(App) + '|' + BoolToStr(DoubleSided, '1', '0') + '|' + IntToStr(Ord(G.ColorType)) + '|' +
    IntToStr(Ord(G.ColorMode)) + '|' + BoolToStr(Lines, '1', '0') + '|' + IntToStr(Ord(AC)) + '|' +
    BoolToStr(G.ForceUnlit, '1', '0');
  if MatCache.TryGetValue(Key, Result) then
    Exit;

  GM := TPasGLTF.TMaterial.Create(Doc);
  if Mat <> nil then
    GM.Name := Mat.X3DName;
  GM.DoubleSided := DoubleSided;

  Unlit := Lines or G.ForceUnlit or (Mat = nil) or (Mat is TUnlitMaterialNode);
  MainTex := Shape.State.MainTexture;
  BaseTex := GetTexture(MainTex);
  Base := Vector4(1, 1, 1, 1);

  if Unlit then
  begin
    Inc(NUnlitMaterials);
    if G.ForceUnlit then
      Base := G.ForcedUnlitColor
    else
    if Mat is TUnlitMaterialNode then
    begin
      Base := Vector4(TUnlitMaterialNode(Mat).EmissiveColor, 1 - TUnlitMaterialNode(Mat).Transparency);
    end;
    { Color / ColorRGBA replace emissive in unlit; COLOR_0 multiplies, so start from white }
    if G.ColorType <> ctNone then
      Base := Vector4(1, 1, 1, Base.W);
    GM.PBRMetallicRoughness.BaseColorFactor := V4G(Vector4(Lin(Base.X), Lin(Base.Y), Lin(Base.Z), Base.W));
    GM.PBRMetallicRoughness.MetallicFactor := 0;
    GM.PBRMetallicRoughness.RoughnessFactor := 0.9;
    GM.Extensions.Add('KHR_materials_unlit', TPasJSONItemObject.Create);
    UseExt('KHR_materials_unlit');
    if BaseTex >= 0 then
      SetTexInfo(GM.PBRMetallicRoughness.BaseColorTexture, BaseTex, App);
  end else
  if Mat is TPhysicalMaterialNode then
  begin
    Phys := TPhysicalMaterialNode(Mat);
    Base := Vector4(Phys.BaseColor, 1 - Phys.Transparency);
    { physical colours are linear already: never converted }
    if (G.ColorType <> ctNone) and (G.ColorMode = cmReplace) then
      Base := Vector4(1, 1, 1, Base.W);
    GM.PBRMetallicRoughness.BaseColorFactor := V4G(Base);
    GM.PBRMetallicRoughness.MetallicFactor := Phys.Metallic;
    GM.PBRMetallicRoughness.RoughnessFactor := Phys.Roughness;
    GM.EmissiveFactor := V3G(Phys.EmissiveColor);
    if BaseTex >= 0 then
      SetTexInfo(GM.PBRMetallicRoughness.BaseColorTexture, BaseTex, App);
    T := GetTexture(Phys.MetallicRoughnessTexture);
    if T >= 0 then
      SetTexInfo(GM.PBRMetallicRoughness.MetallicRoughnessTexture, T, App);
    T := GetTexture(Phys.OcclusionTexture);
    if T >= 0 then
    begin
      SetTexInfo(GM.OcclusionTexture, T, App);
      GM.OcclusionTexture.Strength := Phys.OcclusionStrength;
    end;
    T := GetTexture(Phys.NormalTexture);
    if T >= 0 then
      SetTexInfo(GM.NormalTexture, T, App);
    T := GetTexture(Phys.EmissiveTexture);
    if T >= 0 then
    begin
      SetTexInfo(GM.EmissiveTexture, T, App);
      GM.EmissiveFactor := V3G(Vector3(1, 1, 1));
    end;
  end else
  begin
    { classic Material (Phong), display-space colours }
    Phong := TMaterialNode(Mat);
    Base := Vector4(Phong.DiffuseColor, 1 - Phong.Transparency);
    if (G.ColorType <> ctNone) and (G.ColorMode = cmReplace) then
      Base := Vector4(1, 1, 1, Base.W)
    else
      Base := Vector4(Lin(Base.X), Lin(Base.Y), Lin(Base.Z), Base.W);
    GM.PBRMetallicRoughness.BaseColorFactor := V4G(Base);
    if Phong.Shininess > 0 then
      Roughness := 1 - Sqrt(Phong.Shininess)
    else
      Roughness := 1;
    GM.PBRMetallicRoughness.RoughnessFactor := Roughness;
    GM.PBRMetallicRoughness.MetallicFactor := 0;
    Em := Phong.EmissiveColor;
    GM.EmissiveFactor := V3G(Vector3(Lin(Em.X), Lin(Em.Y), Lin(Em.Z)));
    if BaseTex >= 0 then
      SetTexInfo(GM.PBRMetallicRoughness.BaseColorTexture, BaseTex, App);
    T := GetTexture(Phong.NormalTexture);
    if T >= 0 then
      SetTexInfo(GM.NormalTexture, T, App);
    T := GetTexture(Phong.EmissiveTexture);
    if T >= 0 then
    begin
      SetTexInfo(GM.EmissiveTexture, T, App);
      GM.EmissiveFactor := V3G(Vector3(1, 1, 1));
    end;
    if Opt.PhongSpecular then
    begin
      { glTF dielectric F0 is 0.04; X3D classic specularColor is what actually shines.
        specularColorFactor = specularColor / 0.04 reproduces F0 = specularColor. }
      Spec := Phong.SpecularColor;
      Ext := TPasJSONItemObject.Create;
      if (Spec.X + Spec.Y + Spec.Z) <= 1e-4 then
        Ext.Add('specularFactor', TPasJSONItemNumber.Create(0))
      else
      begin
        SpecArr := TPasJSONItemArray.Create;
        SpecArr.Add(TPasJSONItemNumber.Create(Min(Lin(Spec.X) / 0.04, Opt.SpecularMaxF0 / 0.04)));
        SpecArr.Add(TPasJSONItemNumber.Create(Min(Lin(Spec.Y) / 0.04, Opt.SpecularMaxF0 / 0.04)));
        SpecArr.Add(TPasJSONItemNumber.Create(Min(Lin(Spec.Z) / 0.04, Opt.SpecularMaxF0 / 0.04)));
        Ext.Add('specularColorFactor', SpecArr);
      end;
      GM.Extensions.Add('KHR_materials_specular', Ext);
      UseExt('KHR_materials_specular');
    end;
  end;

  { normal map (Castle / X3D 4 Appearance.normalMap) }
  if (not Unlit) and (App <> nil) and (App.NormalMap <> nil) and
     (GM.NormalTexture.Index < 0) then
  begin
    T := GetTexture(App.NormalMap);
    if T >= 0 then
      SetTexInfo(GM.NormalTexture, T, App);
  end;

  { alpha }
  AlphaMode := TPasGLTF.TMaterial.TAlphaMode.Opaque;
  if (App <> nil) and (App.AlphaMode <> amAuto) then
  begin
    case App.AlphaMode of
      amMask: AlphaMode := TPasGLTF.TMaterial.TAlphaMode.Mask;
      amBlend: AlphaMode := TPasGLTF.TMaterial.TAlphaMode.Blend;
    end;
  end else
  begin
    case AC of
      acBlending: AlphaMode := TPasGLTF.TMaterial.TAlphaMode.Blend;
      acTest: AlphaMode := TPasGLTF.TMaterial.TAlphaMode.Mask;
    end;
  end;
  GM.AlphaMode := AlphaMode;
  if AlphaMode = TPasGLTF.TMaterial.TAlphaMode.Mask then
  begin
    if App <> nil then
      GM.AlphaCutOff := App.AlphaCutoff
    else
      GM.AlphaCutOff := 0.5;
  end;

  Doc.Materials.Add(GM);
  Result := Doc.Materials.Count - 1;
  Inc(NMaterials);
  MatCache.Add(Key, Result);
end;

{ Shapes --------------------------------------------------------------------- }

procedure TExporter.ExportShape(const Shape: TShape; const Index: Integer);
var
  G: TGeometryArrays;
  N, I, K, Total, GroupStart, GroupLen, Gi: Integer;
  Pos, Nor, Col, UV: TSingleArray;
  Idx: TCardArray;
  IdxCount: Integer;
  V3: TVector3;
  V4: TVector4;
  Lines, Points, HasNormals, HasUV, HasCol, Flip: Boolean;
  Prim: TPasGLTF.TMesh.TPrimitive;
  Mesh: TPasGLTF.TMesh;
  GNode: TPasGLTF.TNode;
  MatIdx, Acc: Integer;
  M: TPasGLTF.TMatrix4x4;
  Nm: String;
  TexGen: TGeometryTexCoord;
  Sv: TVector4;
  P: TVector3;
  Count: TCardinalList;
  WorldM: TMatrix4;
  MA, MB, MC, CBC, CCA, CAB, Nn: TVector3;
  Det, Luma: Single;
  Bake, HasTangent: Boolean;
  Tan: TSingleArray;
  V4t: TVector4;

  function IdxAt(const KK: Integer): UInt32;
  begin
    if G.Indexes <> nil then
      Result := G.Indexes[KK]
    else
      Result := KK;
  end;

  procedure AddIdx(const A: UInt32);
  begin
    if IdxCount >= Length(Idx) then
      SetLength(Idx, Max(64, Length(Idx) * 2));
    Idx[IdxCount] := A;
    Inc(IdxCount);
  end;

  procedure AddTri(const A, B, C: UInt32);
  begin
    AddIdx(A);
    if Flip then begin AddIdx(C); AddIdx(B); end
    else begin AddIdx(B); AddIdx(C); end;
  end;

  procedure ProcessGroup(const S, L: Integer);
  var
    J: Integer;
  begin
    case G.Primitive of
      gpTriangles:
        begin
          J := 0;
          while J + 2 < L do
          begin
            AddTri(IdxAt(S + J), IdxAt(S + J + 1), IdxAt(S + J + 2));
            Inc(J, 3);
          end;
        end;
      gpTriangleFan:
        for J := 1 to L - 2 do
          AddTri(IdxAt(S), IdxAt(S + J), IdxAt(S + J + 1));
      gpTriangleStrip:
        for J := 0 to L - 3 do
          if J mod 2 = 0 then
            AddTri(IdxAt(S + J), IdxAt(S + J + 1), IdxAt(S + J + 2))
          else
            AddTri(IdxAt(S + J + 1), IdxAt(S + J), IdxAt(S + J + 2));
      gpLines:
        begin
          J := 0;
          while J + 1 < L do
          begin
            AddIdx(IdxAt(S + J));
            AddIdx(IdxAt(S + J + 1));
            Inc(J, 2);
          end;
        end;
      gpLineStrip, gpLineLoop:
        begin
          for J := 0 to L - 2 do
          begin
            AddIdx(IdxAt(S + J));
            AddIdx(IdxAt(S + J + 1));
          end;
          if (G.Primitive = gpLineLoop) and (L > 2) then
          begin
            AddIdx(IdxAt(S + L - 1));
            AddIdx(IdxAt(S));
          end;
        end;
      gpPoints:
        for J := 0 to L - 1 do
          AddIdx(IdxAt(S + J));
    end;
  end;

begin
  if (not Opt.TextQuads) and (Shape.OriginalGeometry is TTextNode) then
  begin
    Inc(NShapesSkipped);
    Inc(NTextSkipped);
    Warn('Text not exported (Castle gives glyph-cell quads without the font atlas): ' + Shape.NiceName);
    Exit;
  end;
  G := Shape.GeometryArrays;
  try
    N := G.Count;
    if N <= 0 then
    begin
      Inc(NShapesSkipped);
      Warn('shape with no vertices skipped: ' + Shape.NiceName);
      Exit;
    end;
    Lines := G.Primitive in [gpLines, gpLineStrip, gpLineLoop];
    Points := G.Primitive = gpPoints;
    Flip := not G.FrontFaceCcw;

    SetLength(Pos, N * 3);
    for I := 0 to N - 1 do
    begin
      V3 := G.Position(I)^;
      Pos[I * 3] := V3.X; Pos[I * 3 + 1] := V3.Y; Pos[I * 3 + 2] := V3.Z;
    end;

    HasNormals := false;
    if not (Lines or Points) then
    begin
      SetLength(Nor, N * 3);
      for I := 0 to N - 1 do
      begin
        V3 := G.Normal(I)^;
        Nor[I * 3] := V3.X; Nor[I * 3 + 1] := V3.Y; Nor[I * 3 + 2] := V3.Z;
        if (V3.X <> 0) or (V3.Y <> 0) or (V3.Z <> 0) then
          HasNormals := true;
      end;
    end;

    { world matrix: glTF node matrices must be TRS-decomposable (no shear, no zero scale).
      Nested non-uniform scale + rotation gives shear once flattened; bake those shapes
      into the vertices instead (exact; costs nothing but the node matrix). }
    WorldM := Shape.State.Transformation.Transform;
    MA := Vector3(WorldM.Columns[0].X, WorldM.Columns[0].Y, WorldM.Columns[0].Z);
    MB := Vector3(WorldM.Columns[1].X, WorldM.Columns[1].Y, WorldM.Columns[1].Z);
    MC := Vector3(WorldM.Columns[2].X, WorldM.Columns[2].Y, WorldM.Columns[2].Z);
    CBC := TVector3.CrossProduct(MB, MC);
    CCA := TVector3.CrossProduct(MC, MA);
    CAB := TVector3.CrossProduct(MA, MB);
    Det := TVector3.DotProduct(MA, CBC);
    Bake := (MA.Length < 1e-9) or (MB.Length < 1e-9) or (MC.Length < 1e-9) or
      (Abs(TVector3.DotProduct(MA, MB)) > 1e-4 * MA.Length * MB.Length) or
      (Abs(TVector3.DotProduct(MA, MC)) > 1e-4 * MA.Length * MC.Length) or
      (Abs(TVector3.DotProduct(MB, MC)) > 1e-4 * MB.Length * MC.Length) or
      (Abs(WorldM.Columns[0].W) > 1e-6) or (Abs(WorldM.Columns[1].W) > 1e-6) or
      (Abs(WorldM.Columns[2].W) > 1e-6) or (Abs(WorldM.Columns[3].W - 1) > 1e-6);
    if Bake then
    begin
      for I := 0 to N - 1 do
      begin
        V3 := WorldM.MultPoint(Vector3(Pos[I * 3], Pos[I * 3 + 1], Pos[I * 3 + 2]));
        Pos[I * 3] := V3.X; Pos[I * 3 + 1] := V3.Y; Pos[I * 3 + 2] := V3.Z;
      end;
      if Det < 0 then
        Flip := not Flip;
      Inc(NBaked);
      Log('world matrix not TRS-decomposable (shear): baked into vertices');
    end;
    if HasNormals then
      for I := 0 to N - 1 do
      begin
        V3 := Vector3(Nor[I * 3], Nor[I * 3 + 1], Nor[I * 3 + 2]);
        if Bake then
        begin
          Nn := CBC * V3.X + CCA * V3.Y + CAB * V3.Z;
          if Det < 0 then
            Nn := -Nn;
          V3 := Nn;
        end;
        if V3.Length > 1e-12 then
          V3 := V3.Normalize
        else
          V3 := Vector3(0, 1, 0);
        Nor[I * 3] := V3.X; Nor[I * 3 + 1] := V3.Y; Nor[I * 3 + 2] := V3.Z;
      end;

    { material first: it decides whether UVs are worth writing }
    MatIdx := GetMaterial(Shape, G, Lines or Points);
    if not (Lines or Points or G.ForceUnlit) and (Shape.OriginalState.ShapeNode <> nil) and
       (Shape.OriginalState.ShapeNode.Appearance <> nil) then
    begin
      if Shape.OriginalState.ShapeNode.Appearance.Material is TPhysicalMaterialNode then
        Inc(NLitPhysical)
      else
      if Shape.OriginalState.ShapeNode.Appearance.Material is TMaterialNode then
      begin
        Inc(NLitClassic);
        V3 := TMaterialNode(Shape.OriginalState.ShapeNode.Appearance.Material).DiffuseColor;
        Luma := 0.2126 * V3.X + 0.7152 * V3.Y + 0.0722 * V3.Z;
        if Luma > 0.02 then
        begin
          SetLength(Albedos, Length(Albedos) + 1);
          Albedos[High(Albedos)] := Min(Luma, 1.0);
        end;
      end;
      if not Shape.BoundingBox.IsEmpty then
      begin
        SetLength(Surfaces, Length(Surfaces) + 1);
        Surfaces[High(Surfaces)].Centre := Shape.BoundingBox.Center;
        Surfaces[High(Surfaces)].Half := (Shape.BoundingBox.Data[1] - Shape.BoundingBox.Data[0]).Length * 0.5;
      end;
    end;
    HasUV := false;
    if (Doc.Materials[MatIdx].PBRMetallicRoughness.BaseColorTexture.Index >= 0) or
       (Doc.Materials[MatIdx].NormalTexture.Index >= 0) or
       (Doc.Materials[MatIdx].EmissiveTexture.Index >= 0) or
       (Doc.Materials[MatIdx].OcclusionTexture.Index >= 0) or
       (Doc.Materials[MatIdx].PBRMetallicRoughness.MetallicRoughnessTexture.Index >= 0) then
    begin
      if (G.TexCoords.Count > 0) and (G.TexCoords[0] <> nil) then
      begin
        TexGen := G.TexCoords[0];
        SetLength(UV, N * 2);
        HasUV := true;
        case TexGen.Generation of
          tgExplicit:
            for I := 0 to N - 1 do
            begin
              case TexGen.Dimensions of
                2: begin UV[I * 2] := G.TexCoord2D(0, I)^.X; UV[I * 2 + 1] := G.TexCoord2D(0, I)^.Y; end;
                3: begin UV[I * 2] := G.TexCoord3D(0, I)^.X; UV[I * 2 + 1] := G.TexCoord3D(0, I)^.Y; end;
                4: begin
                     V4 := G.TexCoord4D(0, I)^;
                     if V4.W <> 0 then begin UV[I * 2] := V4.X / V4.W; UV[I * 2 + 1] := V4.Y / V4.W; end
                     else begin UV[I * 2] := V4.X; UV[I * 2 + 1] := V4.Y; end;
                   end;
              end;
              UV[I * 2 + 1] := 1 - UV[I * 2 + 1];
            end;
          tgBounds2d, tgBounds3d:
            for I := 0 to N - 1 do
            begin
              P := G.Position(I)^;
              Sv := TexGen.GenerationBoundsVector[0];
              UV[I * 2] := Sv[0] * P.X + Sv[1] * P.Y + Sv[2] * P.Z + Sv[3];
              Sv := TexGen.GenerationBoundsVector[1];
              UV[I * 2 + 1] := 1 - (Sv[0] * P.X + Sv[1] * P.Y + Sv[2] * P.Z + Sv[3]);
            end;
        else
          begin
            HasUV := false;
            Warn('texture coordinate generation not exported: ' + GetEnumName(TypeInfo(TTextureCoordinateGeneration), Ord(TexGen.Generation)));
          end;
        end;
      end else
        Warn('textured shape without texture coordinates: ' + Shape.NiceName);
    end;

    HasCol := false;
    if G.ColorType = ctRgb then
    begin
      SetLength(Col, N * 3);
      for I := 0 to N - 1 do
      begin
        V3 := G.ColorRgb(I)^;
        Col[I * 3] := Lin(V3.X); Col[I * 3 + 1] := Lin(V3.Y); Col[I * 3 + 2] := Lin(V3.Z);
      end;
      HasCol := true;
    end else
    if G.ColorType = ctRgbAlpha then
    begin
      SetLength(Col, N * 4);
      for I := 0 to N - 1 do
      begin
        V4 := G.ColorRgbAlpha(I)^;
        Col[I * 4] := Lin(V4.X); Col[I * 4 + 1] := Lin(V4.Y); Col[I * 4 + 2] := Lin(V4.Z); Col[I * 4 + 3] := V4.W;
      end;
      HasCol := true;
    end;

    HasTangent := false;
    if G.HasTangent and (Doc.Materials[MatIdx].NormalTexture.Index >= 0) and HasUV and HasNormals then
    begin
      SetLength(Tan, N * 4);
      for I := 0 to N - 1 do
      begin
        V4t := G.Tangent(I)^;
        V3 := Vector3(V4t.X, V4t.Y, V4t.Z);
        if Bake then
        begin
          V3 := MA * V3.X + MB * V3.Y + MC * V3.Z;
          if Det < 0 then
            V4t.W := -V4t.W;
        end;
        if V3.Length > 1e-12 then
          V3 := V3.Normalize
        else
          V3 := Vector3(1, 0, 0);
        Tan[I * 4] := V3.X; Tan[I * 4 + 1] := V3.Y; Tan[I * 4 + 2] := V3.Z;
        if V4t.W < 0 then Tan[I * 4 + 3] := -1 else Tan[I * 4 + 3] := 1;
      end;
      HasTangent := true;
    end;

    { indices }
    IdxCount := 0;
    if G.Indexes <> nil then
      Total := G.Indexes.Count
    else
      Total := N;
    Count := G.Counts;
    if Count <> nil then
    begin
      GroupStart := 0;
      for Gi := 0 to Count.Count - 1 do
      begin
        GroupLen := Count[Gi];
        ProcessGroup(GroupStart, GroupLen);
        GroupStart := GroupStart + GroupLen;
      end;
    end else
      ProcessGroup(0, Total);
    SetLength(Idx, IdxCount);
    if IdxCount = 0 then
    begin
      Inc(NShapesSkipped);
      Warn('shape with no primitives skipped: ' + Shape.NiceName);
      Exit;
    end;

    Prim := TPasGLTF.TMesh.TPrimitive.Create(Doc);
    if Lines then
      Prim.Mode := TPasGLTF.TMesh.TPrimitive.TMode.Lines
    else
    if Points then
      Prim.Mode := TPasGLTF.TMesh.TPrimitive.TMode.Points
    else
      Prim.Mode := TPasGLTF.TMesh.TPrimitive.TMode.Triangles;
    Prim.Material := MatIdx;
    Prim.Attributes.Add('POSITION', AddFloatAccessor(Pos, 3, true));
    if HasNormals then
      Prim.Attributes.Add('NORMAL', AddFloatAccessor(Nor, 3, false));
    if HasTangent then
      Prim.Attributes.Add('TANGENT', AddFloatAccessor(Tan, 4, false));
    if HasUV then
      Prim.Attributes.Add('TEXCOORD_0', AddFloatAccessor(UV, 2, false));
    if HasCol then
    begin
      if G.ColorType = ctRgb then
        Acc := AddFloatAccessor(Col, 3, false)
      else
        Acc := AddFloatAccessor(Col, 4, false);
      Prim.Attributes.Add('COLOR_0', Acc);
    end;
    Prim.Indices := AddIndexAccessor(Idx);

    Nm := '';
    if Shape.OriginalState.ShapeNode <> nil then
      Nm := Shape.OriginalState.ShapeNode.X3DName;
    if Nm = '' then
      Nm := Shape.OriginalGeometry.X3DName;
    if Nm = '' then
      Nm := Format('shape_%d', [Index]);

    Mesh := TPasGLTF.TMesh.Create(Doc);
    Mesh.Name := Nm;
    Mesh.Primitives.Add(Prim);
    Doc.Meshes.Add(Mesh);

    GNode := TPasGLTF.TNode.Create(Doc);
    GNode.Name := Nm;
    GNode.Mesh := Doc.Meshes.Count - 1;
    if not Bake then
    begin
      M := MatToGltf(WorldM);
      if not IsIdentityGltf(M) then
        GNode.Matrix := M;
    end;
    Doc.Nodes.Add(GNode);
    GScene.Nodes.Add(Doc.Nodes.Count - 1);

    Inc(NShapes);
    Inc(NVerts, N);
    if Lines then Inc(NLineSegs, IdxCount div 2)
    else if Points then Inc(NPoints, IdxCount)
    else Inc(NTris, IdxCount div 3);
    if HasCol then Inc(NVertexColourShapes);
    if HasUV then Inc(NTexturedShapes);
    Log(Format('shape %d %s: %d verts, %d indices, mode %d, material %d, uv=%s col=%s nrm=%s',
      [Index, Nm, N, IdxCount, Ord(Prim.Mode), MatIdx, BoolToStr(HasUV, 'y', 'n'),
       BoolToStr(HasCol, 'y', 'n'), BoolToStr(HasNormals, 'y', 'n')]));
  finally FreeAndNil(G) end;
end;

{ Camera and lights ------------------------------------------------------------ }

procedure TExporter.ResolveCamera;
var
  Vp: TAbstractViewpointNode;
  GravityUp: TVector3;
begin
  Vp := nil;
  try
    Vp := Scene.GetPerspectiveViewpoint(CamPos, CamDir, CamUp, GravityUp);
  except
    on E: Exception do
    begin
      Warn('Viewpoint could not be resolved (' + E.ClassName + ': ' + E.Message +
        '), X3D default camera written instead (GeoViewpoint is not supported by Castle)');
      Vp := nil;
    end;
  end;
  CamFov := Pi / 4;
  CamFromViewpoint := Vp <> nil;
  if Vp = nil then
  begin
    { X3D default: Viewpoint at (0 0 10) looking down -Z. Castle would fit the camera instead. }
    CamPos := Vector3(0, 0, 10);
    CamDir := Vector3(0, 0, -1);
    CamUp := Vector3(0, 1, 0);
    Log('no Viewpoint: X3D default (0 0 10)');
  end else
  begin
    if Vp is TViewpointNode then
      CamFov := TViewpointNode(Vp).FieldOfView;
    Log(Format('Viewpoint "%s": fov %.4f rad', [Vp.X3DName, CamFov]));
  end;
end;

{ X3D LOD picks its child by the viewer's distance. Castle does that while rendering; an exporter
  has no render loop, so set each level from the Viewpoint position once. }
procedure TExporter.UpdateLods(const T: TShapeTree);
var
  I: Integer;
  L: TShapeTreeLOD;
begin
  if T is TShapeTreeLOD then
  begin
    L := TShapeTreeLOD(T);
    L.UpdateLevel(L.InverseTransform.MultPoint(CamPos), false);
    Log(Format('LOD "%s": level %d chosen for the viewpoint', [L.Node.X3DName, L.Level]));
  end;
  if T is TShapeTreeGroup then
    for I := 0 to TShapeTreeGroup(T).Children.Count - 1 do
      UpdateLods(TShapeTreeGroup(T).Children[I]);
end;

procedure TExporter.ExportCamera;
var
  Cam: TPasGLTF.TCamera;
  Node: TPasGLTF.TNode;
begin
  Cam := TPasGLTF.TCamera.Create(Doc);
  Cam.Name := 'Viewpoint';
  Cam.Type_ := TPasGLTF.TCamera.TCameraType.Perspective;
  Cam.Perspective.YFov := CamFov;
  Cam.Perspective.ZNear := 0.05;
  Cam.Perspective.ZFar := 10000;
  Cam.Perspective.AspectRatio := 1;
  Doc.Cameras.Add(Cam);
  Node := TPasGLTF.TNode.Create(Doc);
  Node.Name := 'Viewpoint';
  Node.Camera := Doc.Cameras.Count - 1;
  Node.Matrix := BasisMatrix(CamPos, CamDir, CamUp);
  Doc.Nodes.Add(Node);
  CameraNode := Doc.Nodes.Count - 1;
  GScene.Nodes.Add(CameraNode);
  Inc(NCameras);
end;

function TExporter.AddLightNode(const LightIdx: Integer; const M: TPasGLTF.TMatrix4x4;
  const Name: String; const Parent: Integer): Integer;
var
  Node: TPasGLTF.TNode;
  Ext: TPasJSONItemObject;
begin
  Node := TPasGLTF.TNode.Create(Doc);
  Node.Name := Name;
  if not IsIdentityGltf(M) then
    Node.Matrix := M;
  Ext := TPasJSONItemObject.Create;
  Ext.Add('light', TPasJSONItemNumber.Create(LightIdx));
  Node.Extensions.Add('KHR_lights_punctual', Ext);
  Doc.Nodes.Add(Node);
  Result := Doc.Nodes.Count - 1;
  if Parent >= 0 then
    Doc.Nodes[Parent].Children.Add(Result)
  else
    GScene.Nodes.Add(Result);
end;

type
  TLightCollector = class
  public
    Owner: TExporter;
    function Collect(Node: TX3DNode; StateStack: TX3DGraphTraverseStateStack;
      ParentInfo: PTraversingInfo; var TraverseIntoChildren: Boolean): Pointer;
  end;

function NewLightJson(const TypeName, Name: String; const Col: TVector3;
  const Intensity: Single): TPasJSONItemObject;
var
  Arr: TPasJSONItemArray;
begin
  Result := TPasJSONItemObject.Create;
  Result.Add('name', TPasJSONItemString.Create(Name));
  Result.Add('type', TPasJSONItemString.Create(TypeName));
  Arr := TPasJSONItemArray.Create;
  Arr.Add(TPasJSONItemNumber.Create(Col.X));
  Arr.Add(TPasJSONItemNumber.Create(Col.Y));
  Arr.Add(TPasJSONItemNumber.Create(Col.Z));
  Result.Add('color', Arr);
  Result.Add('intensity', TPasJSONItemNumber.Create(Intensity));
end;

function IfThenStr(const B: Boolean; const A, C: String): String;
begin
  if B then Result := A else Result := C;
end;

function IfThenSingle(const B: Boolean; const A, C: Single): Single;
begin
  if B then Result := A else Result := C;
end;

function SrgbEotf(const C: Single): Single;
begin
  if C <= 0.04045 then
    Result := C / 12.92
  else
    Result := Power((C + 0.055) / 1.055, 2.4);
end;

{ Light units. X3D browsers draw a classic Material as albedo * N.L * intensity in display space, with no
  1/d^2 (attenuation field default 1 0 0), and a PhysicalMaterial in glTF units. glTF viewers (Babylon.js,
  Blender, Unreal) light every surface the second way: radiance = albedo/pi * lux * N.L, candela / d^2.
  AUTO mode therefore writes, with level(x) = x for a physical scene and
  pi * lin(min(a x, 1)) / lin(a) for a classic one (a = median classic albedo):
    directional / headlight : level(i)
    point and spot          : physical: i * attenuation(d) ; classic: level(i * attenuation(d)) * d^2
  where d is the light's reference distance (median distance to the lit shapes it reaches).
  The same rule x3d-blender-io's importer applies (finalize_light_units), reached here from the render
  side so the two paths agree. A scene with any PhysicalMaterial counts as physical. }
procedure TExporter.PrepareLightUnits;
var
  I, J: Integer;
  T: Single;
begin
  AutoUnits := Opt.LightScale <= 0;
  EffScale := 1;
  if not AutoUnits then
    EffScale := Opt.LightScale;
  ClassicScene := AutoUnits and (NLitClassic > 0) and (NLitPhysical = 0);
  Typical := 0.8;
  if Length(Albedos) > 0 then
  begin
    for I := 1 to High(Albedos) do
    begin
      T := Albedos[I];
      J := I - 1;
      while (J >= 0) and (Albedos[J] > T) do
      begin
        Albedos[J + 1] := Albedos[J];
        Dec(J);
      end;
      Albedos[J + 1] := T;
    end;
    Typical := Albedos[Length(Albedos) div 2];
  end;
  if AutoUnits then
  begin
    Log(Format('light units AUTO: %s scene (%d classic-Material shapes, %d PhysicalMaterial shapes), median albedo %.3f',
      [IfThenStr(ClassicScene, 'classic', 'physical'), NLitClassic, NLitPhysical, Typical]));
    if (NLitClassic > 0) and (NLitPhysical > 0) then
      Warn('scene mixes classic Material and PhysicalMaterial: physical light units chosen, classic shapes will look darker than in an X3D browser');
  end else
    Log(Format('light units MANUAL: every intensity x %.4f', [EffScale]));
end;

function TExporter.Level(const X: Single): Single;
var
  V: Single;
begin
  V := Max(0, X);
  if not AutoUnits then
    Exit(V * EffScale);
  if not ClassicScene then
    Exit(V);
  Result := Pi * SrgbEotf(Min(Typical * V, 1.0)) / SrgbEotf(Typical);
end;

function TExporter.ReferenceDistance(const Origin: TVector3; const Radius: Single;
  const HasAxis: Boolean; const Axis: TVector3; const CutOff: Single): Single;
var
  I, N: Integer;
  Off: TVector3;
  D: Single;
  Ds: array of Single;
begin
  SetLength(Ds, 0);
  for I := 0 to High(Surfaces) do
  begin
    Off := Surfaces[I].Centre - Origin;
    D := Off.Length;
    if D - Surfaces[I].Half > Radius then
      Continue;
    if HasAxis and (D > Surfaces[I].Half) and
       (TVector3.DotProduct(Off.Normalize, Axis) < Cos(Min(CutOff, Pi / 2))) then
      Continue;
    SetLength(Ds, Length(Ds) + 1);
    Ds[High(Ds)] := Max(D, Surfaces[I].Half);
  end;
  if Length(Ds) = 0 then
    Exit(1.0);
  { insertion sort, median }
  for I := 1 to High(Ds) do
  begin
    D := Ds[I];
    N := I - 1;
    while (N >= 0) and (Ds[N] > D) do
    begin
      Ds[N + 1] := Ds[N];
      Dec(N);
    end;
    Ds[N + 1] := D;
  end;
  N := Length(Ds) div 2;
  if Odd(Length(Ds)) then
    Result := Ds[N]
  else
    Result := 0.5 * (Ds[N - 1] + Ds[N]);
end;

function TLightCollector.Collect(Node: TX3DNode; StateStack: TX3DGraphTraverseStateStack;
  ParentInfo: PTraversingInfo; var TraverseIntoChildren: Boolean): Pointer;
var
  L: TAbstractLightNode;
  LI: TLightInstance;
  J: TPasJSONItemObject;
  Sp: TPasJSONItemObject;
  Nm, Kind: String;
  Inner, Outer, D, Fade, Candela: Single;
  Att: TVector3;
  Up: TVector3;

  { X3D 4.0 17.2.2.3: 1 / max(c1 + c2 d + c3 d^2, 1) }
  function AttenuationAt(const Dist: Single): Single;
  begin
    Result := 1 / Max(Att.X + Att.Y * Dist + Att.Z * Dist * Dist, 1);
  end;

  procedure PointLike(const IsSpot: Boolean);
  var
    Radius: Single;
  begin
    Radius := TAbstractPositionalLightNode(L).Radius;
    Att := TAbstractPositionalLightNode(L).Attenuation;
    if Owner.AutoUnits then
    begin
      D := Owner.ReferenceDistance(LI.Location, Radius, IsSpot, LI.Direction,
        IfThenSingle(IsSpot, TSpotLightNode(L).CutOffAngle, Pi));
      Fade := AttenuationAt(D);
      if Owner.ClassicScene then
        Candela := Owner.Level(L.Intensity * Fade) * D * D
      else
        Candela := L.Intensity * Fade;
    end else
    begin
      D := 0;
      Fade := 1;
      Candela := Owner.Level(L.Intensity);
    end;
    Owner.Log(Format('light %s: reference distance %.3f, attenuation factor %.4f, written %.4f (X3D intensity %.3f)',
      [Nm, D, Fade, Candela, L.Intensity]));
  end;

begin
  Result := nil;
  if not (Node is TAbstractLightNode) then
    Exit;
  L := TAbstractLightNode(Node);
  if not L.IsOn then
    Exit;
  Nm := L.X3DName;
  if Nm = '' then
    Nm := Format('light_%d', [Owner.NLights]);
  LI := L.CreateLightInstance(StateStack.Top.Transformation);
  Up := Vector3(0, 1, 0);
  Kind := L.NiceName;
  if L is TDirectionalLightNode then
  begin
    J := NewLightJson('directional', Nm, L.Color, Owner.Level(L.Intensity));
    Owner.LightsArr.Add(J);
    Owner.AddLightNode(Owner.LightsArr.Count - 1,
      BasisMatrix(Vector3(0, 0, 0), LI.Direction, Up), Nm, -1);
    Owner.Log(Format('light %s: directional, X3D intensity %.3f written %.4f', [Nm, L.Intensity, Owner.Level(L.Intensity)]));
  end else
  if L is TSpotLightNode then
  begin
    Inner := Min(TSpotLightNode(L).BeamWidth, TSpotLightNode(L).CutOffAngle);
    Outer := TSpotLightNode(L).CutOffAngle;
    PointLike(true);
    J := NewLightJson('spot', Nm, L.Color, Candela);
    Sp := TPasJSONItemObject.Create;
    Sp.Add('innerConeAngle', TPasJSONItemNumber.Create(Inner));
    Sp.Add('outerConeAngle', TPasJSONItemNumber.Create(Outer));
    J.Add('spot', Sp);
    if TAbstractPositionalLightNode(L).Radius > 0 then
      J.Add('range', TPasJSONItemNumber.Create(TAbstractPositionalLightNode(L).Radius));
    Owner.LightsArr.Add(J);
    Owner.AddLightNode(Owner.LightsArr.Count - 1,
      BasisMatrix(LI.Location, LI.Direction, Up), Nm, -1);
  end else
  if L is TAbstractPositionalLightNode then
  begin
    PointLike(false);
    J := NewLightJson('point', Nm, L.Color, Candela);
    if TAbstractPositionalLightNode(L).Radius > 0 then
      J.Add('range', TPasJSONItemNumber.Create(TAbstractPositionalLightNode(L).Radius));
    Owner.LightsArr.Add(J);
    Owner.AddLightNode(Owner.LightsArr.Count - 1,
      BasisMatrix(LI.Location, Vector3(0, 0, -1), Up), Nm, -1);
  end else
  begin
    Owner.Warn('light type not exported: ' + Kind);
    Exit;
  end;
  Inc(Owner.NLights);
  if (L is TDirectionalLightNode) and (not L.Global) then
    Owner.Log(Format('light %s: global=false (X3D scopes it to its parent group; glTF lights are global)', [Nm]));
end;

procedure TExporter.ExportLights;
var
  Col: TLightCollector;
  J: TPasJSONItemObject;
  Ext: TPasJSONItemObject;
begin
  PrepareLightUnits;
  LightsArr := TPasJSONItemArray.Create;
  Col := TLightCollector.Create;
  try
    Col.Owner := Self;
    if Scene.RootNode <> nil then
      Scene.RootNode.Traverse(TAbstractLightNode, @Col.Collect);
  finally FreeAndNil(Col) end;
  { X3D headlight: a directional light in view space, white, intensity 1, down -Z }
  if Opt.Headlight and Scene.HeadlightOn and (CameraNode >= 0) then
  begin
    J := NewLightJson('directional', 'Headlight', Vector3(1, 1, 1), Level(1.0));
    LightsArr.Add(J);
    AddLightNode(LightsArr.Count - 1, BasisMatrix(Vector3(0, 0, 0), Vector3(0, 0, -1), Vector3(0, 1, 0)),
      'Headlight', CameraNode);
    { child of the camera node: its own matrix is relative to the camera, identity = looks down camera -Z }
    HeadlightWritten := true;
    Inc(NLights);
    Log('headlight written as a directional light under the camera node');
  end;
  if LightsArr.Count = 0 then
  begin
    FreeAndNil(LightsArr);
    Exit;
  end;
  Ext := TPasJSONItemObject.Create;
  Ext.Add('lights', LightsArr);
  LightsArr := nil;
  Doc.Extensions.Add('KHR_lights_punctual', Ext);
  if Doc.ExtensionsUsed.IndexOf('KHR_lights_punctual') < 0 then
    Doc.ExtensionsUsed.Add('KHR_lights_punctual');
end;

{ Driver ----------------------------------------------------------------------- }

function JsonStr(const S: String): String;
begin
  Result := '"' + StringReplace(StringReplace(S, '\', '\\', [rfReplaceAll]), '"', '\"', [rfReplaceAll]) + '"';
end;

function TExporter.JsonReport(const InUrl, OutFile: String): String;
var
  I: Integer;
  ColourName, LightUnitsName: String;
begin
  if Opt.ColourSpace = csSrgb then ColourName := 'srgb' else ColourName := 'as-is';
  if not AutoUnits then LightUnitsName := 'manual' else if ClassicScene then LightUnitsName := 'auto-classic' else LightUnitsName := 'auto-physical';
  Result := '{' + LineEnding +
    '  "input": ' + JsonStr(ExtractFileName(InUrl)) + ',' + LineEnding +
    '  "output": ' + JsonStr(ExtractFileName(OutFile)) + ',' + LineEnding +
    '  "exporter": "x3d-castle-convert (shape-tree exporter on TShape.GeometryArrays)",' + LineEnding +
    '  "shapes": ' + IntToStr(NShapes) + ',' + LineEnding +
    '  "shapes_skipped": ' + IntToStr(NShapesSkipped) + ',' + LineEnding +
    '  "text_shapes_skipped": ' + IntToStr(NTextSkipped) + ',' + LineEnding +
    '  "shapes_baked_for_shear": ' + IntToStr(NBaked) + ',' + LineEnding +
    '  "vertices": ' + IntToStr(NVerts) + ',' + LineEnding +
    '  "triangles": ' + IntToStr(NTris) + ',' + LineEnding +
    '  "line_segments": ' + IntToStr(NLineSegs) + ',' + LineEnding +
    '  "points": ' + IntToStr(NPoints) + ',' + LineEnding +
    '  "materials": ' + IntToStr(NMaterials) + ',' + LineEnding +
    '  "unlit_materials": ' + IntToStr(NUnlitMaterials) + ',' + LineEnding +
    '  "textures": ' + IntToStr(NTextures) + ',' + LineEnding +
    '  "images": ' + IntToStr(NImages) + ',' + LineEnding +
    '  "image_bytes": ' + IntToStr(ImageBytes) + ',' + LineEnding +
    '  "shapes_with_vertex_colours": ' + IntToStr(NVertexColourShapes) + ',' + LineEnding +
    '  "shapes_with_uvs": ' + IntToStr(NTexturedShapes) + ',' + LineEnding +
    '  "lights": ' + IntToStr(NLights) + ',' + LineEnding +
    '  "headlight": ' + BoolToStr(HeadlightWritten, 'true', 'false') + ',' + LineEnding +
    '  "cameras": ' + IntToStr(NCameras) + ',' + LineEnding +
    '  "light_units": ' + JsonStr(LightUnitsName) + ',' + LineEnding +
    '  "lit_classic_shapes": ' + IntToStr(NLitClassic) + ',' + LineEnding +
    '  "lit_physical_shapes": ' + IntToStr(NLitPhysical) + ',' + LineEnding +
    '  "colour_space": ' + JsonStr(ColourName) + ',' + LineEnding +
    '  "warnings": [';
  for I := 0 to Warnings.Count - 1 do
  begin
    if I > 0 then Result := Result + ', ';
    Result := Result + JsonStr(Warnings[I]);
  end;
  Result := Result + ']' + LineEnding + '}' + LineEnding;
end;

function TExporter.Run(const InUrl, OutFile: String): Boolean;
var
  Shapes: TShapeList;
  I: Integer;
  Stream: TFileStream;
  IsBinary: Boolean;
  Rep: TStringList;
begin
  Result := false;
  Scene := TCastleSceneCore.Create(nil);
  Doc := TPasGLTF.TDocument.Create;
  try
    Scene.Load(InUrl);
    Doc.Asset.Version := '2.0';
    Doc.Asset.Generator := 'x3d-castle-convert (Castle Game Engine shape-tree exporter)';
    Buf := TPasGLTF.TBuffer.Create(Doc);
    Doc.Buffers.Add(Buf);
    GScene := TPasGLTF.TScene.Create(Doc);
    GScene.Name := 'Scene';
    Doc.Scenes.Add(GScene);
    Doc.Scene := 0;

    ResolveCamera;
    UpdateLods(Scene.Shapes);
    Shapes := Scene.Shapes.TraverseList(true);
    Log(Format('%d active shapes', [Shapes.Count]));
    for I := 0 to Shapes.Count - 1 do
      ExportShape(Shapes[I], I);
    if Opt.Camera or Opt.Headlight then
      ExportCamera;
    if Opt.Lights or Opt.Headlight then
      ExportLights;

    Align4;
    if Buf.Data.Size = 0 then
    begin
      { glTF requires byteLength >= 1; a scene with no geometry still gets a valid buffer }
      I := 0;
      Buf.Data.WriteBuffer(I, 4);
    end;
    Buf.ByteLength := Buf.Data.Size;
    IsBinary := LowerCase(ExtractFileExt(OutFile)) <> '.gltf';
    if not IsBinary then
      Buf.SetEmbeddedResourceData;
    Stream := TFileStream.Create(OutFile, fmCreate);
    try
      Doc.SaveToStream(Stream, IsBinary, not IsBinary);
    finally FreeAndNil(Stream) end;

    Rep := TStringList.Create;
    try
      Rep.Text := JsonReport(InUrl, OutFile);
      Rep.SaveToFile(OutFile + '.export.json');
    finally FreeAndNil(Rep) end;
    Result := true;
  finally
    FreeAndNil(Doc);
    FreeAndNil(Scene);
  end;
end;

function ExportScene(const InUrl, OutFile: String; const Opt: TExportOptions): Boolean;
var
  E: TExporter;
begin
  E := TExporter.Create;
  try
    E.Opt := Opt;
    Result := E.Run(InUrl, OutFile);
  finally FreeAndNil(E) end;
end;

end.
