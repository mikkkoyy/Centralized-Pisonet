using System.Text.Json.Serialization;

namespace PisoNet.Client.Core;

// Wire DTOs for the versioned station API (protocol v1).
// Property names match the server's JSON schema exactly.

/// <summary>Station enrollment request.</summary>
/// <param name="StationCode">Station identifier (1-32 chars).</param>
/// <param name="EnrollmentSecret">Server enrollment secret (16-256 chars).</param>
/// <param name="DisplayName">Optional human-readable name.</param>
/// <param name="MacAddress">Never sent: MAC addresses are
/// informational metadata, not proof of identity.</param>
public sealed record RegisterRequest(
    [property: JsonPropertyName("station_code")] string StationCode,
    [property: JsonPropertyName("enrollment_secret")] string EnrollmentSecret,
    [property: JsonPropertyName("display_name")] string? DisplayName,
    [property: JsonPropertyName("mac_address")] string? MacAddress);

/// <summary>Enrollment response. The token is issued exactly once.</summary>
/// <param name="StationId">Server-side station row id.</param>
/// <param name="StationCode">Station identifier.</param>
/// <param name="Token">One-time bearer token (secret).</param>
/// <param name="ProtocolVersion">Protocol version the server accepted.</param>
/// <param name="EnrolledAt">Unix epoch seconds of enrollment.</param>
public sealed record RegisterResponse(
    [property: JsonPropertyName("station_id")] int StationId,
    [property: JsonPropertyName("station_code")] string StationCode,
    [property: JsonPropertyName("token")] string Token,
    [property: JsonPropertyName("protocol_version")] int ProtocolVersion,
    [property: JsonPropertyName("enrolled_at")] long EnrolledAt);

/// <summary>Heartbeat request body (version declaration).</summary>
/// <param name="ProtocolVersion">Protocol version.</param>
public sealed record HeartbeatRequest(
    [property: JsonPropertyName("protocol_version")] int ProtocolVersion);

/// <summary>Active session state as reported by the server.</summary>
/// <param name="SessionId">Session row id.</param>
/// <param name="State">Session state ("active").</param>
/// <param name="GrantedSeconds">Total paid seconds granted.</param>
/// <param name="StartedAt">Unix epoch seconds when the session started.</param>
/// <param name="RemainingSeconds">Server-authoritative remaining seconds.</param>
public sealed record SessionStateDto(
    [property: JsonPropertyName("session_id")] int SessionId,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("granted_seconds")] int GrantedSeconds,
    [property: JsonPropertyName("started_at")] long StartedAt,
    [property: JsonPropertyName("remaining_seconds")] int RemainingSeconds);

/// <summary>Pending station command delivered with a heartbeat.</summary>
/// <param name="Id">Command id (acknowledged by this id).</param>
/// <param name="CommandType">Command type ("lock" or "unlock").</param>
/// <param name="Payload">Optional command payload.</param>
/// <param name="ExpiresAt">Unix epoch seconds after which the command is void.</param>
public sealed record PendingCommandDto(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("command_type")] string CommandType,
    [property: JsonPropertyName("payload")] string? Payload,
    [property: JsonPropertyName("expires_at")] long ExpiresAt);

/// <summary>Heartbeat response: server-authoritative station state.</summary>
/// <param name="StationCode">Station identifier.</param>
/// <param name="ProtocolVersion">Protocol version in use.</param>
/// <param name="ServerTime">Server time (Unix epoch seconds).</param>
/// <param name="StationState">available | occupied | offline | revoked.</param>
/// <param name="Lock">Session lock: locked | unlocked.</param>
/// <param name="Session">Active session, or null when none.</param>
/// <param name="Commands">Pending commands awaiting acknowledgement.</param>
public sealed record HeartbeatResponse(
    [property: JsonPropertyName("station_code")] string StationCode,
    [property: JsonPropertyName("protocol_version")] int ProtocolVersion,
    [property: JsonPropertyName("server_time")] long ServerTime,
    [property: JsonPropertyName("station_state")] string StationState,
    [property: JsonPropertyName("lock")] string Lock,
    [property: JsonPropertyName("session")] SessionStateDto? Session,
    [property: JsonPropertyName("commands")] IReadOnlyList<PendingCommandDto>? Commands);

/// <summary>Command acknowledgement response.</summary>
/// <param name="Acknowledged">True when the command was acknowledged.</param>
/// <param name="CommandId">Acknowledged command id.</param>
public sealed record CommandAckResponse(
    [property: JsonPropertyName("acknowledged")] bool Acknowledged,
    [property: JsonPropertyName("command_id")] long CommandId);
