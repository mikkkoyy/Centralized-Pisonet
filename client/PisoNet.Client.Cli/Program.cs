using PisoNet.Client.Core;

internal static class Program
{
    private const int ExitOk = 0;
    private const int ExitUsage = 1;
    private const int ExitAuth = 2;

    private static async Task<int> Main(string[] args)
    {
        if (args.Length == 0)
        {
            PrintUsage();
            return ExitUsage;
        }

        return args[0].ToLowerInvariant() switch
        {
            "enroll" => await RunEnrollAsync(args.Skip(1).ToArray()),
            "run" => await RunRunAsync(),
            "reset" => RunReset(),
            _ => PrintUsageAndReturnExitCode(),
        };
    }

    private static async Task<int> RunEnrollAsync(string[] args)
    {
        string? serverUrl = null;
        string? stationCode = null;
        string? displayName = null;
        string? enrollmentSecret = Environment.GetEnvironmentVariable("PISONET_ENROLLMENT_SECRET");

        for (var i = 0; i < args.Length; i++)
        {
            var argument = args[i].ToLowerInvariant();
            var value = i + 1 < args.Length ? args[i + 1] : null;
            switch (argument)
            {
                case "--server":
                    serverUrl = value;
                    i++;
                    break;
                case "--station":
                    stationCode = value;
                    i++;
                    break;
                case "--display-name":
                    displayName = value;
                    i++;
                    break;
                case "--secret":
                    enrollmentSecret = value;
                    i++;
                    break;
                default:
                    Console.Error.WriteLine($"Unknown option: {args[i]}");
                    return ExitUsage;
            }
        }

        if (string.IsNullOrEmpty(enrollmentSecret))
        {
            Console.Error.WriteLine(
                "Enrollment secret is required: pass --secret <secret> " +
                "or set PISONET_ENROLLMENT_SECRET.");
            return ExitUsage;
        }

        if (enrollmentSecret.Length < 16 || enrollmentSecret.Length > 256)
        {
            Console.Error.WriteLine(
                "Enrollment secret must be 16-256 characters.");
            return ExitUsage;
        }

        var configuration = new ClientConfiguration
        {
            ServerUrl = serverUrl ?? string.Empty,
            StationCode = stationCode ?? string.Empty,
            DisplayName = displayName,
        };

        var errors = configuration.Validate();
        if (errors.Count > 0)
        {
            foreach (var error in errors)
            {
                Console.Error.WriteLine($"Configuration error: {error}");
            }
            return ExitUsage;
        }

        using var apiClient = new StationApiClient(configuration);
        RegisterResponse registration;
        try
        {
            registration = await apiClient.RegisterAsync(enrollmentSecret);
        }
        catch (EnrollmentRejectedException exception)
        {
            Console.Error.WriteLine($"Enrollment rejected: {exception.Message}");
            return ExitUsage;
        }
        catch (DuplicateStationException exception)
        {
            Console.Error.WriteLine(
                $"Station code already enrolled: {exception.Message} " +
                "Use 'run' with the existing credential, or reset and re-enroll with a new code.");
            return ExitUsage;
        }
        catch (StationProtocolException exception)
        {
            Console.Error.WriteLine($"Server error (HTTP {exception.StatusCode}): {exception.Message}");
            return ExitUsage;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Could not reach the server: {exception.Message}");
            return ExitUsage;
        }

        new ConfigurationStore().Save(configuration);
        new DpapiCredentialStore().Save(
            new StationCredentials(registration.StationCode, registration.Token));

        Console.WriteLine(
            $"Enrolled station '{registration.StationCode}' (id {registration.StationId}). " +
            "Credential stored in protected per-user storage.");
        return ExitOk;
    }

    private static async Task<int> RunRunAsync()
    {
        var configuration = new ConfigurationStore().Load();
        if (configuration is null)
        {
            Console.Error.WriteLine(
                "Not configured. Run 'piso-client enroll --server <url> --station <code> --secret <secret>' first.");
            return ExitUsage;
        }

        if (!new DpapiCredentialStore().TryLoad(out var credentials) || credentials is null)
        {
            Console.Error.WriteLine(
                "No stored station credential (or it cannot be decrypted by this user). " +
                "Re-run 'enroll' to register this station.");
            return ExitUsage;
        }

        var errors = configuration.Validate();
        if (errors.Count > 0)
        {
            foreach (var error in errors)
            {
                Console.Error.WriteLine($"Configuration error: {error}");
            }
            return ExitUsage;
        }

        var state = new StationStateModel
        {
            StationCode = credentials.StationCode,
        };

        using var apiClient = new StationApiClient(configuration);
        apiClient.SetStationToken(credentials.Token);

        var countdown = new SessionCountdown();
        var commandProcessor = new CommandProcessor(apiClient, state);
        var heartbeatService = new HeartbeatService(
            configuration, apiClient, state, countdown, commandProcessor);
        heartbeatService.StateChanged += () => PrintState(state);

        using var shutdown = new CancellationTokenSource();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            shutdown.Cancel();
        };

        heartbeatService.Start();
        try
        {
            while (!shutdown.IsCancellationRequested && !heartbeatService.IsHalted)
            {
                await Task.Delay(500, shutdown.Token);
            }
        }
        catch (OperationCanceledException)
        {
            // Shutdown requested.
        }

        await heartbeatService.StopAsync();
        await heartbeatService.DisposeAsync();

        if (heartbeatService.IsHalted && state.Connection == ConnectionState.AuthenticationFailed)
        {
            return ExitAuth;
        }

        return ExitOk;
    }

    private static int RunReset()
    {
        new ConfigurationStore().Clear();
        new DpapiCredentialStore().Clear();
        Console.WriteLine("Local configuration and stored credential cleared.");
        return ExitOk;
    }

    private static void PrintState(StationStateModel state)
    {
        var session = state.SessionStatus switch
        {
            SessionStatus.Active => $"session {state.CurrentRemainingSeconds}s remaining",
            SessionStatus.Terminated => "session ended",
            _ => "no session",
        };

        Console.WriteLine(
            $"[{state.Connection}] {state.Message} | {state.StationState} | " +
            $"{session}{(state.IsAdminLocked ? " | locked by administrator" : string.Empty)}");
    }

    private static void PrintUsage() => Console.WriteLine(
        "MKY PisoNet Station Client\n" +
        "Usage:\n" +
        "  piso-client enroll --server <url> --station <code> [--display-name <name>] [--secret <secret>]\n" +
        "  piso-client run\n" +
        "  piso-client reset\n" +
        "\nThe enrollment secret can also be provided via PISONET_ENROLLMENT_SECRET.");

    private static int PrintUsageAndReturnExitCode()
    {
        PrintUsage();
        return ExitUsage;
    }
}
