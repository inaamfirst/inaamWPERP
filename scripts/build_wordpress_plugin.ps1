$ErrorActionPreference = "Stop"

$RepositoryRoot = (Get-Location).Path
$PluginName = "choiceoye-erp-product-videos"
$Version = "1.0.0"
$PluginRoot = Join-Path $RepositoryRoot "integrations\wordpress\$PluginName"
$ReleaseRoot = Join-Path $RepositoryRoot "release_builds\wordpress"
$ArchivePath = Join-Path $ReleaseRoot "$PluginName-$Version.zip"
$StagingRoot = Join-Path $ReleaseRoot ("staging-" + [guid]::NewGuid().ToString("N"))
$StagedPlugin = Join-Path $StagingRoot $PluginName

if (-not (Test-Path -LiteralPath $PluginRoot)) {
    throw "WordPress plugin directory is missing: $PluginRoot"
}

& (Join-Path $RepositoryRoot "scripts\test_wordpress_plugin.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
try {
    New-Item -ItemType Directory -Force -Path $StagedPlugin | Out-Null
    Get-ChildItem -LiteralPath $PluginRoot -Force | Where-Object { $_.Name -ne "tests" } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $StagedPlugin -Recurse -Force
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }
    $archive = [System.IO.Compression.ZipFile]::Open(
        $ArchivePath,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        Get-ChildItem -LiteralPath $StagedPlugin -Recurse -File | ForEach-Object {
            $entryName = $_.FullName.Substring($StagingRoot.Length).TrimStart('\', '/') -replace '\\', '/'
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $_.FullName,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
    }

    $readArchive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entries = @($readArchive.Entries | ForEach-Object { $_.FullName })
        if ($entries.Count -eq 0 -or ($entries | Where-Object { $_ -like '*\*' })) {
            throw "Generated plugin ZIP has invalid or empty entry paths."
        }
        if (-not ($entries -contains "$PluginName/$PluginName.php")) {
            throw "Generated plugin ZIP is missing its main plugin file."
        }
    }
    finally {
        $readArchive.Dispose()
    }
}
finally {
    $ResolvedRelease = [System.IO.Path]::GetFullPath($ReleaseRoot)
    $ResolvedStaging = [System.IO.Path]::GetFullPath($StagingRoot)
    if ($ResolvedStaging.StartsWith($ResolvedRelease + [System.IO.Path]::DirectorySeparatorChar)) {
        Remove-Item -LiteralPath $ResolvedStaging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "WordPress plugin package created: $ArchivePath"
