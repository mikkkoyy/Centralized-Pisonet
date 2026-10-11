namespace PisoNet.Client.Core;

/// <summary>Base class for protocol-level errors with an HTTP status code.</summary>
public class StationProtocolException : Exception
{
    /// <summary>HTTP status code returned by the server.</summary>
    public int StatusCode { get; }

    /// <summary>Creates a protocol-level error.</summary>
    /// <param name="message">Operator-facing message (never contains secrets).</param>
    /// <param name="statusCode">HTTP status code.</param>
    public StationProtocolException(string message, int statusCode)
        : base(message) => StatusCode = statusCode;
}

/// <summary>The server rejected the station credentials (401): revoked, rotated, or unknown.</summary>
public sealed class StationAuthenticationException : StationProtocolException
{
    /// <summary>Creates an authentication failure.</summary>
    /// <param name="message">Operator-facing message.</param>
    public StationAuthenticationException(string message)
        : base(message, 401) { }
}

/// <summary>The server rejected the enrollment secret (403).</summary>
public sealed class EnrollmentRejectedException : StationProtocolException
{
    /// <summary>Creates an enrollment rejection.</summary>
    /// <param name="message">Operator-facing message.</param>
    public EnrollmentRejectedException(string message)
        : base(message, 403) { }
}

/// <summary>The station code already exists (409).</summary>
public sealed class DuplicateStationException : StationProtocolException
{
    /// <summary>Creates a duplicate-station error.</summary>
    /// <param name="message">Operator-facing message.</param>
    public DuplicateStationException(string message)
        : base(message, 409) { }
}

/// <summary>The server rejected the request as a protocol or validation error (400).</summary>
public sealed class ProtocolVersionMismatchException : StationProtocolException
{
    /// <summary>Creates a protocol/validation rejection.</summary>
    /// <param name="message">Operator-facing message.</param>
    public ProtocolVersionMismatchException(string message)
        : base(message, 400) { }
}

/// <summary>
/// The server could not be reached: network failure, DNS,
/// connection refused, or HTTP timeout. Never raised for HTTP
/// error statuses (those raise typed protocol exceptions).
/// </summary>
public sealed class ServerUnavailableException : Exception
{
    /// <summary>Creates a server-unavailable error.</summary>
    /// <param name="message">Operator-facing message.</param>
    /// <param name="innerException">Underlying transport exception, if any.</param>
    public ServerUnavailableException(string message, Exception? innerException = null)
        : base(message, innerException) { }
}
