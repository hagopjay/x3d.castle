{ x3d-castle-convert: load any model Castle reads (X3D, glTF, ...) and save it as glTF / GLB.

  Default writer: X3DCastleExport (shape-tree exporter on Castle's render arrays).
  --engine-writer: Castle's stock glTF writer (SaveNode), kept as the baseline for comparisons.

  Usage: x3d-castle-convert in.x3d out.glb [options]
    --engine-writer          use Castle's stock writer instead
    --colour-space=as-is|srgb  classic (display-space) colours to linear for glTF (default srgb)
    --no-camera --no-lights --no-headlight --no-textures
    --no-phong-specular      do not write KHR_materials_specular for classic Material
    --specular-max-f0=F      cap on the F0 asked of KHR_materials_specular (default 0.5)
    --text-quads             keep Text as untextured glyph-cell quads (off by default: Text is skipped)
    --light-scale=F          multiply X3D light intensity (default auto: pi for classic-Material scenes, 1 for PhysicalMaterial)
    --text-atlas             Text as glyph quads textured with Castle's font atlas, alpha blended (default: Text is skipped)
    --hidden-switch          also write unselected Switch choices, as nodes with KHR_node_visibility visible=false
    --scope-lights           global=false point/spot lights: clamp the glTF range to the extent of their scope
    --verbose }
program x3d_castle_convert;
{$mode objfpc}{$H+}
{$ifdef MSWINDOWS} {$apptype CONSOLE} {$endif}
uses SysUtils, CastleUtils, CastleLog, CastleApplicationProperties, X3DNodes, X3DLoad,
  X3DCastleExport;
var
  Root: TX3DRootNode;
  Opt: TExportOptions;
  InFile, OutFile, Arg: String;
  EngineWriter: Boolean;
  I, NPos: Integer;
begin
  Opt := DefaultExportOptions;
  EngineWriter := false;
  InFile := '';
  OutFile := '';
  NPos := 0;
  for I := 1 to ParamCount do
  begin
    Arg := ParamStr(I);
    if Arg = '--engine-writer' then EngineWriter := true
    else if Arg = '--no-camera' then Opt.Camera := false
    else if Arg = '--no-lights' then Opt.Lights := false
    else if Arg = '--no-headlight' then Opt.Headlight := false
    else if Arg = '--no-textures' then Opt.Textures := false
    else if Arg = '--no-phong-specular' then Opt.PhongSpecular := false
    else if Copy(Arg, 1, 18) = '--specular-max-f0=' then Opt.SpecularMaxF0 := StrToFloat(Copy(Arg, 19, Length(Arg)))
    else if Arg = '--text-quads' then Opt.TextQuads := true
    else if Arg = '--text-atlas' then Opt.TextAtlas := true
    else if Arg = '--hidden-switch' then Opt.HiddenSwitch := true
    else if Arg = '--scope-lights' then Opt.ScopeLights := true
    else if Arg = '--verbose' then Opt.Verbose := true
    else if Arg = '--colour-space=srgb' then Opt.ColourSpace := csSrgb
    else if Arg = '--colour-space=as-is' then Opt.ColourSpace := csAsIs
    else if Copy(Arg, 1, 14) = '--light-scale=' then Opt.LightScale := StrToFloat(Copy(Arg, 15, Length(Arg)))
    else if Copy(Arg, 1, 2) = '--' then
    begin
      Writeln(ErrOutput, 'Unknown option: ', Arg);
      Halt(2);
    end else
    begin
      Inc(NPos);
      if NPos = 1 then InFile := Arg else OutFile := Arg;
    end;
  end;
  if NPos <> 2 then
  begin
    Writeln('Usage: x3d-castle-convert in.x3d out.glb [--engine-writer] [--colour-space=as-is|srgb] ',
      '[--no-camera] [--no-lights] [--no-headlight] [--no-textures] [--no-phong-specular] [--specular-max-f0=F] [--text-quads] ',
      '[--text-atlas] [--hidden-switch] [--scope-lights] [--light-scale=F] [--verbose]');
    Halt(2);
  end;
  ApplicationProperties.OnWarning.Add(@ApplicationProperties.WriteWarningOnConsole);
  if EngineWriter then
  begin
    Root := LoadNode(InFile);
    try
      SaveNode(Root, OutFile, 'x3d-castle-convert (Castle Game Engine glTF writer)', InFile);
    finally FreeAndNil(Root); end;
  end else
  try
    if not ExportScene(InFile, OutFile, Opt) then
      Halt(1);
  except
    on E: Exception do
    begin
      { a file the engine cannot read is a failed conversion, not a crash }
      Writeln(ErrOutput, 'x3d-castle-convert: ', E.ClassName, ': ', E.Message);
      Halt(1);
    end;
  end;
end.
