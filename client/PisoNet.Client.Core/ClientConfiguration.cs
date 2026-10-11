using System.Text.RegularExpressions;

namespace PisoNet.Client.Core;

/// <summary>
/// Client configuration. Validated before every connection attempt;
/// nothing is hardcoded and no production addresses are embedded.
/// Immutable, so copies can be derived with <c>with</c>.
/// </summary>
public sealed record class ClientConfiguration
{
    /// <summary>Fastest allowed heartbeat interval.</summary>
    public static readonly TimeSpan MinHeartbeatInterval = TimeSpan.FromSeconds(5);

    /// <summary>Slowest allowed heartbeat interval.</summary>
    public static readonly TimeSpan MaxHeartbeatInterval = TimeSpan.FromSeconds(60);

    /// <summary>
    /// The server considers a station stale after 30 seconds without a
    /// heartbeat (STATION_HEARTBEAT_TIMEOUT). The default client interval
    /// is one third of that, leaving two chances before the station is
    /// marked offline.
    /// </summary>
    public static readonly TimeSpan DefaultHeartbeatInterval = TimeSpan.FromSeconds(10);
    /// <summary>Default HTTP request timeout.</summary>
    public static readonly TimeSpan DefaultHttpTimeout = TimeSpan.FromSeconds(10);

    // Matches the server's station_code validation pattern.
    private static readonly Regex StationCodePattern =
        new("^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$", RegexOptions.Compiled);

    /// <summary>Server base URL (absolute http or https).</summary>
    public string ServerUrl { get; init; } = string.Empty;

    /// <summary>Station identifier (1-32 chars, server-validated).</summary>
    public string StationCode { get; init; } = string.Empty;

    /// <summary>Optional human-readable display name.</summary>
    public string? DisplayName { get; init; }

    /// <summary>Interval between heartbeats while connected.</summary>
    public TimeSpan HeartbeatInterval { get; init; } = DefaultHeartbeatInterval;

    /// <summary>HTTP request timeout.</summary>
    public TimeSpan HttpTimeout { get; init; } = DefaultHttpTimeout;

    /// <summary>Returns a list of human-readable validation errors (empty when valid).</summary>
    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();

        if (!Uri.TryCreate(ServerUrl, UriKind.Absolute, out var uri)
            || uri.Scheme is not ("http" or "https"))
        {
            errors.Add("Server URL must be an absolute http:// or https:// URL.");
        }

        if (string.IsNullOrWhiteSpace(StationCode))
        {
            errors.Add("Station code is required.");
        }
        else if (!StationCodePattern.IsMatch(StationCode))
        {
            errors.Add(
                "Station code must be 1-32 characters: letters, digits, dash or " +
                "underscore, starting with a letter or digit.");
        }

        if (HeartbeatInterval < MinHeartbeatInterval || HeartbeatInterval > MaxHeartbeatInterval)
        {
            errors.Add(
                $"Heartbeat interval must be between {MinHeartbeatInterval.TotalSeconds:0} " +
                $"and {MaxHeartbeatInterval.TotalSeconds:0} seconds.");
        }

        if (HttpTimeout < TimeSpan.FromSeconds(1) || HttpTimeout > TimeSpan.FromSeconds(120))
        {
            errors.Add("HTTP timeout must be between 1 and 120 seconds.");
        }

        return errors;
    }

    /// <summary>True when there are no validation errors.</summary>
    public bool IsValid => Validate().Count == 0;
}
