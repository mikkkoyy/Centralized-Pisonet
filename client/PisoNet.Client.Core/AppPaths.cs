namespace PisoNet.Client.Core;

/// <summary>Application data locations (per-user, under LocalApplicationData).</summary>
public static class AppPaths
{
    private static readonly string BaseDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "MKY",
        "PisoNet");

    /// <summary>Per-user application data directory (created on demand).</summary>
    public static string DataDirectory
    {
        get
        {
            Directory.CreateDirectory(BaseDirectory);
            return BaseDirectory;
        }
    }

    /// <summary>Plain configuration (server URL, station code). Never holds secrets.</summary>
    public static string ConfigFilePath => Path.Combine(DataDirectory, "config.json");

    /// <summary>DPAPI-protected station credentials.</summary>
    public static string CredentialFilePath => Path.Combine(DataDirectory, "station.credentials");
}
