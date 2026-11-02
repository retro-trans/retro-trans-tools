// GPL-3.0-or-later. Process bridge to unmodified Universal Dreamcast Patcher 2.1.8.
using System.Security.Cryptography;
using System.Text.Json;
using UniversalDreamcastPatcher.Core;
using UniversalDreamcastPatcher.Core.Patching;

internal static class Program
{
    static void Emit(object value) => Console.WriteLine(JsonSerializer.Serialize(value));
    sealed class Progress : IProgress<string>
    {
        public void Report(string text) => Emit(new { progress = text });
    }
    static Dictionary<string, object> Files(string root) => Directory.GetFiles(root, "*", SearchOption.AllDirectories)
        .OrderBy(p => p, StringComparer.Ordinal).ToDictionary(
            p => Path.GetRelativePath(root, p).Replace('\\', '/'),
            p => { using var f = File.OpenRead(p); return (object)new { bytes = f.Length, sha256 = Convert.ToHexString(SHA256.HashData(f)).ToLowerInvariant() }; });

    public static async Task<int> Main(string[] args)
    {
        using var cancel = new CancellationTokenSource();
        try
        {
            if (args.Length < 2) throw new Exception("Expected a command and JSON request.");
            using var doc = JsonDocument.Parse(File.ReadAllText(args[1]));
            string Get(string key) => doc.RootElement.GetProperty(key).GetString()!;
            using var timer = new Timer(_ => { if (File.Exists(Get("cancel_file"))) cancel.Cancel(); }, null, 0, 100);
            var progress = new Progress();
            switch (args[0])
            {
                case "inspect":
                {
                    var normalized = await InputNormalizer.NormalizeAsync(Get("source"), Get("workspace"), progress, cancel.Token);
                    if (!normalized.Success) throw new Exception(normalized.ErrorMessage);
                    var r = await GdiReader.ExtractAsync(normalized.GdiPath, Get("extracted"), progress, cancel.Token);
                    if (!r.Success) throw new Exception(r.ErrorMessage);
                    Emit(new { success = true, files = Files(r.ExtractedRoot), gdi = normalized.GdiPath });
                    break;
                }
                case "build":
                {
                    var r = await PatchBuilder.BuildAsync(new PatchBuildOptions {
                        OriginalGdiPath = Get("source"), ModifiedGdiPath = Get("target"), OutputDcpPath = Get("output"),
                        IncludeCustomIpBin = true, IpBinFrom = IpBinSource.ModifiedGdi
                    }, progress, cancel.Token);
                    if (!r.Success) throw new Exception(r.ErrorMessage);
                    Emit(new { success = true, output = r.ProducedDcpPath, files_diffed = r.FilesDiffed, files_added = r.FilesAddedVerbatim });
                    break;
                }
                case "apply":
                {
                    var format = Get("format") switch { "GDI" => OutputDiscImageFormat.Gdi, "CUE/BIN" => OutputDiscImageFormat.CueBin, "CHD" => OutputDiscImageFormat.ChdGdRom, _ => throw new Exception("Unsupported output format.") };
                    var r = await PatchApplier.ApplyAsync(new PatchApplyOptions {
                        SourceDiscImagePath = Get("source"), DcpPatchPath = Get("patch"), OutputFolder = Get("output"),
                        OutputFormat = format,
                        // Fail rather than silently choose when a custom IP.BIN has ambiguous track data.
                        PreserveCustomIpBinAsync = () => throw new Exception("Ambiguous custom IP.BIN track data; use Universal Dreamcast Patcher to review this patch.")
                    }, progress, cancel.Token);
                    if (!r.Success) throw new Exception(r.ErrorMessage);
                    Emit(new { success = true, output = r.ProducedOutputFolder, files_patched = r.FilesPatched, files_added = r.FilesAdded, files_overwritten = r.FilesOverwritten });
                    break;
                }
                default: throw new Exception("Unknown command.");
            }
            return 0;
        }
        catch (Exception e) { Emit(new { success = false, error = e.Message }); return 1; }
    }
}
