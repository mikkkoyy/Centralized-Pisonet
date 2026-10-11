namespace PisoNet.Client.Core;

/// <summary>Station credential issued by the server at enrollment.</summary>
/// <param name="StationCode">Station identifier (not secret).</param>
/// <param name="Token">Per-station bearer token (secret).</param>
public sealed record StationCredentials(string StationCode, string Token);
