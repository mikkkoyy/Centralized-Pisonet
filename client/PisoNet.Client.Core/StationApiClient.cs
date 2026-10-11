using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace PisoNet.Client.Core;

/// <summary>
/// Typed client for the PISO-002 versioned station API.
/// Sends <c>X-Api-Version: 1</c> on every request and the
/// per-station bearer token once enrollment has issued one.
/// Never logs or includes the token in exception messages.
/// </summary>
public sealed class StationApiClient : IDisposable
{
    /// <summary>Station API protocol version sent in X-Api-Version.</summary>
    public const int ProtocolVersion = 1;

    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _httpClient;
    private readonly ClientConfiguration _configuration;
    private readonly bool _ownsHttpClient;
    private string? _stationToken;

    /// <summary>Creates a station API client.</summary>
    /// <param name="configuration">Validated client configuration.</param>
    /// <param name="handler">
    /// Injectable handler for testing. When provided, the handler
    /// is not disposed with this client.
    /// </param>
    public StationApiClient(ClientConfiguration configuration, HttpMessageHandler? handler = null)
    {
        ArgumentNullException.ThrowIfNull(configuration);

        _configuration = configuration;
        _httpClient = handler is null
            ? new HttpClient()
            : new HttpClient(handler, disposeHandler: false);
        _ownsHttpClient = handler is null;

        _httpClient.BaseAddress = new Uri(configuration.ServerUrl.TrimEnd('/') + "/");
        _httpClient.Timeout = configuration.HttpTimeout;
        _httpClient.DefaultRequestHeaders.Add("X-Api-Version", ProtocolVersion.ToString());
    }

    /// <summary>Sets (or clears, with null) the station bearer token.</summary>
    /// <param name="token">Bearer token issued at enrollment.</param>
    public void SetStationToken(string? token) => _stationToken = token;

    /// <summary>
    /// Enrolls the station with the server enrollment secret.
    /// The issued token is returned exactly once.
    /// </summary>
    public async Task<RegisterResponse> RegisterAsync(
        string enrollmentSecret,
        CancellationToken cancellationToken = default)
    {
        // MAC addresses are informational metadata on the server and
        // are never accepted as proof of identity, so the client
        // deliberately does not send one.
        var request = new RegisterRequest(
            _configuration.StationCode,
            enrollmentSecret,
            _configuration.DisplayName,
            null);

        var response = await _httpClient.PostAsJsonAsync(
            "api/v1/stations/register", request, cancellationToken);
        return await HandleResponseAsync<RegisterResponse>(response, cancellationToken);
    }

    /// <summary>
    /// Authenticated heartbeat poll. Never creates sessions and
    /// never awards time; it returns server-authoritative state.
    /// </summary>
    public async Task<HeartbeatResponse> HeartbeatAsync(CancellationToken cancellationToken = default)
    {
        var request = new HeartbeatRequest(ProtocolVersion);
        var response = await PostAuthorizedAsync(
            $"api/v1/stations/{Uri.EscapeDataString(_configuration.StationCode)}/heartbeat",
            request,
            cancellationToken);
        return await HandleResponseAsync<HeartbeatResponse>(response, cancellationToken);
    }

    /// <summary>Acknowledges delivery of a pending command.</summary>
    public async Task<CommandAckResponse> AcknowledgeCommandAsync(
        long commandId,
        CancellationToken cancellationToken = default)
    {
        var response = await PostAuthorizedAsync(
            $"api/v1/stations/{Uri.EscapeDataString(_configuration.StationCode)}/commands/{commandId}/ack",
            null,
            cancellationToken);
        return await HandleResponseAsync<CommandAckResponse>(response, cancellationToken);
    }

    /// <summary>
    /// Posts a JSON body with the station bearer token when one
    /// has been issued. Registration deliberately omits the token
    /// (it does not exist yet).
    /// </summary>
    private async Task<HttpResponseMessage> PostAuthorizedAsync(
        string relativeUrl,
        object? body,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, relativeUrl)
        {
            Content = body is null
                ? null
                : JsonContent.Create(body, options: SerializerOptions),
        };
        if (_stationToken is not null)
        {
            request.Headers.Authorization =
                new AuthenticationHeaderValue("Bearer", _stationToken);
        }

        return await _httpClient.SendAsync(request, cancellationToken);
    }

    private async Task<T> HandleResponseAsync<T>(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode)
        {
            T? payload;
            try
            {
                payload = await response.Content.ReadFromJsonAsync<T>(
                    SerializerOptions, cancellationToken);
            }
            catch (JsonException)
            {
                throw new StationProtocolException(
                    "The server returned a malformed response body.",
                    (int)response.StatusCode);
            }

            if (payload is null)
            {
                throw new StationProtocolException(
                    "The server returned an empty response body.",
                    (int)response.StatusCode);
            }
            return payload;
        }

        var detail = await ReadDetailAsync(response, cancellationToken);
        switch (response.StatusCode)
        {
            case HttpStatusCode.Unauthorized:
                throw new StationAuthenticationException(
                    detail ?? "The server rejected the station credentials.");
            case HttpStatusCode.Forbidden:
                throw new EnrollmentRejectedException(
                    detail ?? "The server rejected the enrollment secret.");
            case HttpStatusCode.Conflict:
                throw new DuplicateStationException(
                    detail ?? "The station code already exists.");
            case HttpStatusCode.BadRequest:
                throw new ProtocolVersionMismatchException(
                    detail ?? "The server rejected the request (protocol or validation error).");
            case HttpStatusCode.NotFound:
                throw new StationProtocolException(
                    detail ?? "The server could not find the requested resource.",
                    (int)response.StatusCode);
            default:
                throw new StationProtocolException(
                    detail is null
                        ? $"The server returned an unexpected status ({response.StatusCode})."
                        : $"The server rejected the request (HTTP {(int)response.StatusCode}): {detail}",
                    (int)response.StatusCode);
        }
    }

    private static async Task<string?> ReadDetailAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = await response.Content.ReadAsStreamAsync(
                cancellationToken);
            using var document = await JsonDocument.ParseAsync(
                stream, cancellationToken: cancellationToken);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("detail", out var detail))
            {
                return null;
            }

            return detail.ValueKind switch
            {
                JsonValueKind.String => detail.GetString(),
                JsonValueKind.Array => string.Join(
                    "; ", detail.EnumerateArray().Select(DescribeError)),
                _ => null,
            };
        }
        catch (JsonException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }
    }

    /// <summary>
    /// Renders one FastAPI validation error. The "input"
    /// member is deliberately excluded: it echoes the
    /// submitted value, which may be the enrollment secret.
    /// </summary>
    private static string DescribeError(JsonElement error)
    {
        var message = error.TryGetProperty("msg", out var msg)
            ? msg.GetString()
            : null;
        var location = error.TryGetProperty("loc", out var loc) && loc.ValueKind == JsonValueKind.Array
            ? string.Join(
                ".",
                loc.EnumerateArray()
                    .Select(part => part.ValueKind == JsonValueKind.String
                        ? part.GetString()
                        : string.Empty))
            : null;

        if (location is null)
        {
            return message ?? "invalid request";
        }
        return message is null ? location : $"{location}: {message}";
    }

    /// <summary>Disposes the HTTP client when this instance owns it.</summary>
    public void Dispose()
    {
        if (_ownsHttpClient)
        {
            _httpClient.Dispose();
        }
    }
}
