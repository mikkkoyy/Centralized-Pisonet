using System.Text.Json;

namespace PisoNet.Client.Core;

/// <summary>
/// Stores plain (non-secret) client configuration as JSON.
/// Credentials are stored separately by <see cref="ICredentialStore"/>.
/// </summary>
public sealed class ConfigurationStore
{
    private readonly string _filePath;

    /// <summary>Creates a store, optionally at a custom path.</summary>
    /// <param name="filePath">Config file path; defaults to <see cref="AppPaths.ConfigFilePath"/>.</param>
    public ConfigurationStore(string? filePath = null)
    {
        _filePath = filePath ?? AppPaths.ConfigFilePath;
    }

    /// <summary>Loads the configuration, or null when absent or unreadable.</summary>
    public ClientConfiguration? Load()
    {
        if (!File.Exists(_filePath))
        {
            return null;
        }

        ConfigurationDto? dto;
        try
        {
            dto = JsonSerializer.Deserialize<ConfigurationDto>(File.ReadAllText(_filePath));
        }
        catch (JsonException)
        {
            return null;
        }

        if (dto is null || string.IsNullOrWhiteSpace(dto.ServerUrl) || string.IsNullOrWhiteSpace(dto.StationCode))
        {
            return null;
        }

        return new ClientConfiguration
        {
            ServerUrl = dto.ServerUrl,
            StationCode = dto.StationCode,
            DisplayName = dto.DisplayName,
            HeartbeatInterval = dto.HeartbeatIntervalSeconds > 0
                ? TimeSpan.FromSeconds(dto.HeartbeatIntervalSeconds)
                : ClientConfiguration.DefaultHeartbeatInterval,
            HttpTimeout = dto.HttpTimeoutSeconds > 0
                ? TimeSpan.FromSeconds(dto.HttpTimeoutSeconds)
                : ClientConfiguration.DefaultHttpTimeout,
        };
    }

    /// <summary>Persists the configuration as JSON.</summary>
    /// <param name="configuration">Configuration to store.</param>
    public void Save(ClientConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(configuration);

        var dto = new ConfigurationDto
        {
            ServerUrl = configuration.ServerUrl,
            StationCode = configuration.StationCode,
            DisplayName = configuration.DisplayName,
            HeartbeatIntervalSeconds = (int)Math.Round(configuration.HeartbeatInterval.TotalSeconds),
            HttpTimeoutSeconds = (int)Math.Round(configuration.HttpTimeout.TotalSeconds),
        };

        var json = JsonSerializer.Serialize(dto);
        File.WriteAllText(_filePath, json);
    }

    /// <summary>Deletes the stored configuration file.</summary>
    public void Clear()
    {
        if (File.Exists(_filePath))
        {
            File.Delete(_filePath);
        }
    }

    private sealed class ConfigurationDto
    {
        public string? ServerUrl { get; set; }
        public string? StationCode { get; set; }
        public string? DisplayName { get; set; }
        public int HeartbeatIntervalSeconds { get; set; }
        public int HttpTimeoutSeconds { get; set; }
    }
}
