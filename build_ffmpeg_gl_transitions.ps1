#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$FFmpegRepo = "https://github.com/ShiftMediaProject/FFmpeg.git",
    [string]$FFmpegRef = "master",
    [string]$SourcesDir,
    [string]$FFmpegDir,
    [string]$GLTransitionRepo = "https://github.com/adnahmed/ffmpeg-gl-transition.git",
    [string]$GLTransitionDir,
    [string]$VcpkgRoot,
    [string]$Triplet,
    [ValidateSet("x64", "Win32")]
    [string]$Platform = "x64",
    [ValidateSet("Debug", "Release", "DebugDLL", "ReleaseDLL", "DebugDLLStaticDeps", "ReleaseDLLStaticDeps")]
    [string]$Configuration = "ReleaseDLL",
    [switch]$SkipDependencyClone,
    [switch]$SkipVcpkg,
    [switch]$SkipBuildDeps,
    [switch]$SkipShaderSync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info {
    param([string]$Message)
    Write-Host "[ffmpeg-win] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Warning "[ffmpeg-win] $Message"
}

function Invoke-External {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [switch]$IgnoreExit
    )

    $argumentText = if ($Arguments.Count) { $Arguments -join ' ' } else { '' }
    if ($WorkingDirectory) {
        Write-Info "Running: $FilePath $argumentText (cwd=$WorkingDirectory)"
    } else {
        Write-Info "Running: $FilePath $argumentText"
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $argumentText
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    $null = $process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($stdout) { Write-Host $stdout.TrimEnd() }
    if ($stderr) { Write-Warn $stderr.TrimEnd() }

    if (-not $IgnoreExit -and $process.ExitCode -ne 0) {
        throw "Command '$FilePath $argumentText' failed with exit code $($process.ExitCode)."
    }

    return $process.ExitCode
}

function Get-VsDevCmdPath {
    $candidateVswhere = @(
        Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\\Installer\\vswhere.exe',
        Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\\Installer\\vswhere.exe'
    ) | Where-Object { $_ -and (Test-Path $_) }

    if (-not $candidateVswhere) {
        throw 'vswhere.exe not found. Install Visual Studio 2017 or newer with MSBuild tools.'
    }

    $vswhere = $candidateVswhere[0]
    $installPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
    if (-not $installPath) {
        throw 'Visual Studio installation with MSBuild component was not found.'
    }

    $vsDevCmd = Join-Path $installPath 'Common7\Tools\VsDevCmd.bat'
    if (-not (Test-Path $vsDevCmd)) {
        throw "VsDevCmd.bat not found at $vsDevCmd."
    }

    return $vsDevCmd
}

function Invoke-MSBuild {
    param(
        [string]$SolutionPath,
        [string]$VsDevCmd,
        [string]$Configuration,
        [string]$Platform,
        [string]$WorkingDirectory
    )

    if (-not (Test-Path $SolutionPath)) {
        throw "Solution file not found: $SolutionPath"
    }

    $quotedSolution = '"' + $SolutionPath + '"'
    $msbuildCmd = '"' + $VsDevCmd + '" -no_logo && msbuild ' + $quotedSolution + ' /m /t:Build /p:Configuration=' + $Configuration + ' /p:Platform=' + $Platform + ' /p:PreferredToolArchitecture=x64'
    Invoke-External -FilePath 'cmd.exe' -Arguments @('/c', $msbuildCmd) -WorkingDirectory $WorkingDirectory | Out-Null
}

function Ensure-Directory {
    param([string]$Path)
    if (-not $Path) { return }
    if (-not (Test-Path $Path)) {
        Write-Info "Creating directory $Path"
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Sync-GitRepository {
    param(
        [string]$RepositoryUrl,
        [string]$TargetPath,
        [string]$Ref = 'master'
    )

    $parent = Split-Path $TargetPath -Parent
    Ensure-Directory $parent

    if (-not (Test-Path (Join-Path $TargetPath '.git'))) {
        Invoke-External -FilePath 'git' -Arguments @('clone', $RepositoryUrl, $TargetPath) -WorkingDirectory $parent | Out-Null
    } else {
        Invoke-External -FilePath 'git' -Arguments @('fetch', '--all', '--tags') -WorkingDirectory $TargetPath | Out-Null
    }

    Invoke-External -FilePath 'git' -Arguments @('checkout', $Ref) -WorkingDirectory $TargetPath | Out-Null
    $pullExit = Invoke-External -FilePath 'git' -Arguments @('pull', '--ff-only') -WorkingDirectory $TargetPath -IgnoreExit
    if ($pullExit -ne 0) {
        Write-Warn "git pull failed for $TargetPath (likely detached tag); continuing."
    }
}

function Ensure-ClCompileEntry {
    param(
        [string]$PropsPath,
        [string]$IncludePath
    )

    [xml]$propsXml = Get-Content -Path $PropsPath -Raw
    $nsUri = $propsXml.Project.NamespaceURI
    $nsMgr = New-Object System.Xml.XmlNamespaceManager($propsXml.NameTable)
    $nsMgr.AddNamespace('msb', $nsUri)

    $itemGroup = $propsXml.SelectSingleNode("//msb:ItemGroup[msb:ClCompile[@Include='..\\libavfilter\\allfilters.c']]", $nsMgr)
    if (-not $itemGroup) {
        throw 'Failed to locate ClCompile ItemGroup in libavfilter_files.props.'
    }

    $existing = $itemGroup.SelectSingleNode("msb:ClCompile[@Include='$IncludePath']", $nsMgr)
    if ($existing) { return }

    $newNode = $propsXml.CreateElement('ClCompile', $nsUri)
    $null = $newNode.SetAttribute('Include', $IncludePath)
    $null = $itemGroup.AppendChild($newNode)
    $propsXml.Save($PropsPath)
}

function Ensure-LineAfter {
    param(
        [string]$FilePath,
        [string]$Anchor,
        [string]$NewLine
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    (Get-Content -Path $FilePath) | ForEach-Object { $lines.Add($_) }
    if ($lines.Contains($NewLine)) { return }
    $index = $lines.IndexOf($Anchor)
    if ($index -lt 0) {
        throw "Anchor '$Anchor' not found in $FilePath."
    }
    $lines.Insert($index + 1, $NewLine)
    Set-Content -Path $FilePath -Value $lines -Encoding Ascii
}

function Ensure-ConfigDefine {
    param(
        [string]$ConfigPath,
        [string]$Symbol
    )

    $define = "#define $Symbol 1"
    $lines = [System.Collections.Generic.List[string]]::new()
    (Get-Content -Path $ConfigPath) | ForEach-Object { $lines.Add($_) }
    if ($lines.Contains($define)) { return }

    $anchor = '#define CONFIG_GRAPHMONITOR_FILTER 1'
    $index = $lines.IndexOf($anchor)
    if ($index -lt 0) { $index = $lines.Count - 1 }
    $lines.Insert($index + 1, $define)
    Set-Content -Path $ConfigPath -Value $lines -Encoding Ascii
}

function Update-AdditionalDependencies {
    param([string]$ProjectPath)

    [xml]$projXml = Get-Content -Path $ProjectPath -Raw
    $nsUri = $projXml.Project.NamespaceURI
    $nsMgr = New-Object System.Xml.XmlNamespaceManager($projXml.NameTable)
    $nsMgr.AddNamespace('msb', $nsUri)

    $nodes = $projXml.SelectNodes('//msb:AdditionalDependencies', $nsMgr)
    foreach ($node in $nodes) {
        $text = $node.InnerText
        if ($text -match 'glfw3') { continue }

        $itemDefinition = $node.ParentNode
        while ($itemDefinition -and $itemDefinition.Name -ne 'ItemDefinitionGroup') {
            $itemDefinition = $itemDefinition.ParentNode
        }
        $condition = if ($itemDefinition) { $itemDefinition.Attributes['Condition'].Value } else { '' }
        $isDebug = $condition -match 'Debug'

        $libsToAdd = if ($isDebug) { 'glew32d.lib;glfw3.lib;opengl32.lib;' } else { 'glew32.lib;glfw3.lib;opengl32.lib;' }
        if ($text.Contains('%(AdditionalDependencies)')) {
            $node.InnerText = $text.Replace('%(AdditionalDependencies)', $libsToAdd + '%(AdditionalDependencies)')
        } else {
            $separator = if ($text.EndsWith(';')) { '' } else { ';' }
            $node.InnerText = $text + $separator + $libsToAdd
        }
    }

    $projXml.Save($ProjectPath)
}

function Remove-EglDefine {
    param([string]$FilterPath)

    if (-not (Test-Path $FilterPath)) { return }
    $content = Get-Content -Path $FilterPath -Raw
    $updated = $content -replace "#\s*define\s+GL_TRANSITION_USING_EGL\s*\r?\n", ''
    if ($content -ne $updated) {
        Set-Content -Path $FilterPath -Value $updated -Encoding Ascii
    }
}

if (-not $SourcesDir) {
    $SourcesDir = Join-Path $env:USERPROFILE 'ffmpeg_win'
}
Ensure-Directory $SourcesDir

if (-not $FFmpegDir) {
    $FFmpegDir = Join-Path $SourcesDir 'FFmpeg'
}
if (-not $GLTransitionDir) {
    $GLTransitionDir = Join-Path $SourcesDir 'ffmpeg-gl-transition'
}

if (-not $Triplet) {
    $Triplet = if ($Platform -eq 'Win32') { 'x86-windows' } else { 'x64-windows' }
}

if (-not $VcpkgRoot) {
    if ($env:VCPKG_ROOT) {
        $VcpkgRoot = $env:VCPKG_ROOT
    } else {
        $VcpkgRoot = Join-Path $SourcesDir 'vcpkg'
    }
}

Write-Info "Sources directory: $SourcesDir"
Write-Info "FFmpeg directory: $FFmpegDir"
Write-Info "Triplet: $Triplet"
Write-Info "Configuration: $Configuration ($Platform)"

Invoke-External -FilePath 'git' -Arguments @('--version') -IgnoreExit | Out-Null

if (-not $SkipVcpkg) {
    Ensure-Directory (Split-Path $VcpkgRoot -Parent)

    if (-not (Test-Path (Join-Path $VcpkgRoot '.git'))) {
        Invoke-External -FilePath 'git' -Arguments @('clone', 'https://github.com/microsoft/vcpkg.git', $VcpkgRoot) -WorkingDirectory (Split-Path $VcpkgRoot -Parent) | Out-Null
    } else {
        Invoke-External -FilePath 'git' -Arguments @('pull', '--ff-only') -WorkingDirectory $VcpkgRoot | Out-Null
    }

    $bootstrap = Join-Path $VcpkgRoot 'bootstrap-vcpkg.bat'
    if (-not (Test-Path (Join-Path $VcpkgRoot 'vcpkg.exe'))) {
        Invoke-External -FilePath 'cmd.exe' -Arguments @('/c', '"' + $bootstrap + '" -disableMetrics') -WorkingDirectory $VcpkgRoot | Out-Null
    }

    $vcpkgExe = Join-Path $VcpkgRoot 'vcpkg.exe'
    $packages = @("glew:$Triplet", "glfw3:$Triplet")
    foreach ($pkg in $packages) {
        Invoke-External -FilePath $vcpkgExe -Arguments @('install', $pkg, '--triplet', $Triplet) -WorkingDirectory $VcpkgRoot | Out-Null
    }
} else {
    $vcpkgExe = Join-Path $VcpkgRoot 'vcpkg.exe'
    if (-not (Test-Path $vcpkgExe)) {
        throw 'vcpkg.exe not found but SkipVcpkg was specified.'
    }
}

Sync-GitRepository -RepositoryUrl $FFmpegRepo -TargetPath $FFmpegDir -Ref $FFmpegRef
Sync-GitRepository -RepositoryUrl $GLTransitionRepo -TargetPath $GLTransitionDir -Ref 'master'

$vfSource = Join-Path $GLTransitionDir 'vf_gltransition.c'
if (-not (Test-Path $vfSource)) {
    throw 'vf_gltransition.c not found in GL transition repository.'
}

$vfTarget = Join-Path $FFmpegDir 'libavfilter\vf_gltransition.c'
Copy-Item -Path $vfSource -Destination $vfTarget -Force
Remove-EglDefine -FilterPath $vfTarget

$propsPath = Join-Path $FFmpegDir 'SMP\libavfilter_files.props'
Ensure-ClCompileEntry -PropsPath $propsPath -IncludePath '..\libavfilter\vf_gltransition.c'

$allFiltersPath = Join-Path $FFmpegDir 'libavfilter\allfilters.c'
Ensure-LineAfter -FilePath $allFiltersPath -Anchor 'extern const AVFilter ff_vf_graphmonitor;' -NewLine 'extern const AVFilter ff_vf_gltransition;'

$configComponentsPath = Join-Path $FFmpegDir 'SMP\config_components.h'
Ensure-ConfigDefine -ConfigPath $configComponentsPath -Symbol 'CONFIG_GLTRANSITION_FILTER'

$filterListPath = Join-Path $FFmpegDir 'SMP\libavfilter\filter_list.c'
Ensure-LineAfter -FilePath $filterListPath -Anchor '    &ff_vf_graphmonitor,' -NewLine '    &ff_vf_gltransition,'

$libProjectPath = Join-Path $FFmpegDir 'SMP\libavfilter.vcxproj'
Update-AdditionalDependencies -ProjectPath $libProjectPath

$vsDevCmd = Get-VsDevCmdPath

$includeDir = Join-Path $VcpkgRoot ('installed\' + $Triplet + '\include')
$libDir = Join-Path $VcpkgRoot ('installed\' + $Triplet + '\lib')
$binDir = Join-Path $VcpkgRoot ('installed\' + $Triplet + '\bin')
if (-not (Test-Path $includeDir)) { throw "vcpkg include directory not found: $includeDir" }
if (-not (Test-Path $libDir)) { throw "vcpkg lib directory not found: $libDir" }

if (-not ($env:INCLUDE -split ';' | Where-Object { $_ -eq $includeDir })) {
    $env:INCLUDE = $includeDir + ';' + $env:INCLUDE
}
if (-not ($env:LIB -split ';' | Where-Object { $_ -eq $libDir })) {
    $env:LIB = $libDir + ';' + $env:LIB
}
if (Test-Path $binDir) {
    if (-not ($env:PATH -split ';' | Where-Object { $_ -eq $binDir })) {
        $env:PATH = $binDir + ';' + $env:PATH
    }
}

if (-not $SkipDependencyClone) {
    $depsScript = Join-Path $FFmpegDir 'SMP\project_get_dependencies.bat'
    if (Test-Path $depsScript) {
        Invoke-External -FilePath 'cmd.exe' -Arguments @('/c', '"' + $depsScript + '"') -WorkingDirectory (Join-Path $FFmpegDir 'SMP') | Out-Null
    } else {
        Write-Warn 'project_get_dependencies.bat not found; skipping dependency fetch.'
    }
}

if (-not $SkipBuildDeps) {
    $depsSolution = Join-Path $FFmpegDir 'SMP\ffmpeg_deps.sln'
    Invoke-MSBuild -SolutionPath $depsSolution -VsDevCmd $vsDevCmd -Configuration $Configuration -Platform $Platform -WorkingDirectory (Join-Path $FFmpegDir 'SMP')
}

$ffmpegSolution = Join-Path $FFmpegDir 'SMP\ffmpeg.sln'
Invoke-MSBuild -SolutionPath $ffmpegSolution -VsDevCmd $vsDevCmd -Configuration $Configuration -Platform $Platform -WorkingDirectory (Join-Path $FFmpegDir 'SMP')

$outputRoot = Join-Path $FFmpegDir 'msvc'
$archFolder = if ($Platform -eq 'Win32') { 'x86' } else { 'x64' }
$binCandidates = @(
    Join-Path $outputRoot (Join-Path 'bin' $archFolder),
    Join-Path $outputRoot (Join-Path (Join-Path 'bin' $archFolder) $Configuration)
)
$binOutput = $binCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $binOutput) {
    $binOutput = $binCandidates[0]
    Write-Warn "Expected binary output folder not found; using $binOutput as a fallback."
}

if (-not $SkipShaderSync) {
    $shaderRepo = Join-Path $SourcesDir 'gl-transitions'
    if (-not (Test-Path (Join-Path $shaderRepo '.git'))) {
        Invoke-External -FilePath 'git' -Arguments @('clone', 'https://github.com/gl-transitions/gl-transitions.git', $shaderRepo) -WorkingDirectory $SourcesDir | Out-Null
    } else {
        Invoke-External -FilePath 'git' -Arguments @('pull', '--ff-only') -WorkingDirectory $shaderRepo | Out-Null
    }

    if (Test-Path $binOutput) {
        Copy-Item -Path (Join-Path $shaderRepo 'transitions\*') -Destination $binOutput -Recurse -Force
    }
}

$dllSourceDirs = @(
    Join-Path $VcpkgRoot ('installed\' + $Triplet + '\bin'),
    Join-Path $VcpkgRoot ('installed\' + $Triplet + '\debug\bin')
)
if (Test-Path $binOutput) {
    foreach ($dir in $dllSourceDirs) {
        if (Test-Path $dir) {
            Get-ChildItem -Path $dir -Filter 'glew32*.dll' -ErrorAction SilentlyContinue | ForEach-Object {
                Copy-Item -Path $_.FullName -Destination $binOutput -Force
            }
            Get-ChildItem -Path $dir -Filter 'glfw3*.dll' -ErrorAction SilentlyContinue | ForEach-Object {
                Copy-Item -Path $_.FullName -Destination $binOutput -Force
            }
        }
    }
}

$ffmpegExe = Join-Path $binOutput 'ffmpeg.exe'
if (Test-Path $ffmpegExe) {
    Write-Info "Build completed. FFmpeg located at $ffmpegExe"
    try {
        Invoke-External -FilePath $ffmpegExe -Arguments @('-filters') -WorkingDirectory (Split-Path $ffmpegExe) -IgnoreExit | Out-Null
    } catch {
        Write-Warn 'FFmpeg executed but returned an error; inspect the output above if available.'
    }
} else {
    Write-Warn 'FFmpeg executable not found; check msbuild output for details.'
}
