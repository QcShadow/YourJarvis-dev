using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal sealed class JarvisUpdateInfo
{
    public string CurrentVersion;
    public string LatestVersion;
    public string ReleaseUrl;
    public string DownloadUrl;
    public readonly List<string> DownloadUrls = new List<string>();
    public string Sha256;
    public string Notes;
    public bool IsAvailable;
}

internal static class JarvisUpdateChecker
{
    private const string ConfigFile = "app-version.json";

    public static async Task<JarvisUpdateInfo> CheckAsync(string root)
    {
        string configPath = Path.Combine(root, ConfigFile);
        if (!File.Exists(configPath))
            throw new InvalidOperationException("版本配置缺失，请重新安装完整软件包。");

        var serializer = new JavaScriptSerializer();
        var config = serializer.Deserialize<Dictionary<string, object>>(
            File.ReadAllText(configPath));
        string current = GetRequired(config, "version", "本地版本号");
        var manifestUrls = new List<string>();
        if (config.ContainsKey("manifestUrls")) {
            var values = config["manifestUrls"] as object[];
            if (values != null) foreach (object value in values) {
                string address = Convert.ToString(value).Trim();
                if (address.Length > 0) manifestUrls.Add(address);
            } else {
                string address = Convert.ToString(config["manifestUrls"]).Trim();
                if (address.Length > 0) manifestUrls.Add(address);
            }
        }
        if (manifestUrls.Count == 0 && config.ContainsKey("manifestUrl"))
            manifestUrls.Add(Convert.ToString(config["manifestUrl"]).Trim());
        if (manifestUrls.Count == 0) throw new InvalidDataException("更新地址未配置。");

        var candidates = new List<JarvisUpdateInfo>();
        Exception lastError = null;
        using (var handler = new HttpClientHandler { AllowAutoRedirect = true })
        using (var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(10) }) {
            client.DefaultRequestHeaders.UserAgent.ParseAdd("JARVIS-Link/" + current);
            foreach (string manifestUrl in manifestUrls) {
                try {
                    RequireHttps(manifestUrl, "更新地址");
                    string content = await client.GetStringAsync(manifestUrl);
                    var remote = serializer.Deserialize<Dictionary<string, object>>(content);
                    candidates.Add(ParseRemoteUpdate(remote, current));
                } catch (Exception error) { lastError = error; }
            }
        }
        if (candidates.Count == 0) throw new InvalidOperationException("所有更新渠道均不可用。", lastError);
        JarvisUpdateInfo selected = candidates[0];
        foreach (JarvisUpdateInfo candidate in candidates)
            if (CompareVersions(candidate.LatestVersion, selected.LatestVersion) > 0) selected = candidate;
        foreach (JarvisUpdateInfo candidate in candidates) {
            if (CompareVersions(candidate.LatestVersion, selected.LatestVersion) == 0
                && !selected.DownloadUrls.Contains(candidate.DownloadUrl))
                selected.DownloadUrls.Add(candidate.DownloadUrl);
        }
        return selected;
    }

    private static JarvisUpdateInfo ParseRemoteUpdate(Dictionary<string, object> remote, string current)
    {
        string latest = GetRequired(remote, "version", "远程版本号");
        string releaseUrl = GetRequired(remote, "releaseUrl", "发布页面");
        RequireHttps(releaseUrl, "发布页面");
        string downloadUrl = GetRequired(remote, "downloadUrl", "下载地址");
        RequireHttps(downloadUrl, "下载地址");
        string notes = remote.ContainsKey("notes") ? Convert.ToString(remote["notes"]) : "";
        string sha256 = remote.ContainsKey("sha256") ? Convert.ToString(remote["sha256"]).Trim() : "";

        return new JarvisUpdateInfo {
            CurrentVersion = current,
            LatestVersion = latest,
            ReleaseUrl = releaseUrl,
            DownloadUrl = downloadUrl,
            Sha256 = sha256,
            Notes = notes,
            IsAvailable = CompareVersions(latest, current) > 0,
        };
    }

    public static void OpenRelease(string address)
    {
        RequireHttps(address, "发布页面");
        Process.Start(new ProcessStartInfo(address) { UseShellExecute = true });
    }

    public static async Task<string> DownloadAsync(string root, JarvisUpdateInfo update, IProgress<int> progress)
    {
        string updates = Path.Combine(root, "updates");
        Directory.CreateDirectory(updates);
        var downloadUrls = new List<string>(update.DownloadUrls);
        if (downloadUrls.Count == 0) downloadUrls.Add(update.DownloadUrl);
        string name;
        try { name = Path.GetFileName(new Uri(downloadUrls[0]).AbsolutePath); }
        catch { name = "JARVIS-" + update.LatestVersion + ".zip"; }
        if (String.IsNullOrWhiteSpace(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            name = "JARVIS-" + update.LatestVersion + ".zip";
        string destination = Path.Combine(updates, name);
        string partial = destination + ".download";
        Exception lastError = null;
        bool downloaded = false;
        foreach (string downloadUrl in downloadUrls) {
            try {
                if (File.Exists(partial)) File.Delete(partial);
                using (var client = new HttpClient { Timeout = TimeSpan.FromMinutes(30) })
                using (var response = await client.GetAsync(downloadUrl, HttpCompletionOption.ResponseHeadersRead)) {
                    response.EnsureSuccessStatusCode();
                    long total = response.Content.Headers.ContentLength ?? -1;
                    long received = 0;
                    using (var input = await response.Content.ReadAsStreamAsync())
                    using (var output = new FileStream(partial, FileMode.Create, FileAccess.Write, FileShare.None, 1024 * 1024, true)) {
                        byte[] buffer = new byte[1024 * 1024]; int count;
                        while ((count = await input.ReadAsync(buffer, 0, buffer.Length)) > 0) {
                            await output.WriteAsync(buffer, 0, count); received += count;
                            if (total > 0 && progress != null) progress.Report((int)Math.Min(100, received * 100L / total));
                        }
                    }
                }
                downloaded = true; break;
            } catch (Exception error) { lastError = error; }
        }
        if (!downloaded) throw new InvalidOperationException("所有更新下载渠道均不可用。", lastError);
        if (!String.IsNullOrWhiteSpace(update.Sha256)) {
            using (var sha = SHA256.Create()) using (var stream = File.OpenRead(partial)) {
                string actual = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                if (!String.Equals(actual, update.Sha256.Trim().ToLowerInvariant(), StringComparison.Ordinal)) {
                    File.Delete(partial); throw new InvalidDataException("下载包校验失败，文件可能已损坏。");
                }
            }
        }
        if (File.Exists(destination)) File.Delete(destination);
        File.Move(partial, destination);
        return destination;
    }

    internal static int CompareVersions(string left, string right)
    {
        Version leftVersion = ParseVersion(left);
        Version rightVersion = ParseVersion(right);
        return leftVersion.CompareTo(rightVersion);
    }

    private static Version ParseVersion(string value)
    {
        string normalized = (value ?? "").Trim().TrimStart('v', 'V');
        int suffix = normalized.IndexOfAny(new char[] { '-', '+' });
        if (suffix >= 0) normalized = normalized.Substring(0, suffix);
        Version parsed;
        if (!Version.TryParse(normalized, out parsed))
            throw new InvalidDataException("无效版本号：" + value);
        return parsed;
    }

    private static string GetRequired(Dictionary<string, object> data, string key, string label)
    {
        string value = data.ContainsKey(key) ? Convert.ToString(data[key]).Trim() : "";
        if (value.Length == 0) throw new InvalidDataException(label + "未配置。");
        return value;
    }

    private static void RequireHttps(string address, string label)
    {
        Uri uri;
        if (!Uri.TryCreate(address, UriKind.Absolute, out uri) || uri.Scheme != Uri.UriSchemeHttps)
            throw new InvalidDataException(label + "必须是 HTTPS 地址。");
    }
}
