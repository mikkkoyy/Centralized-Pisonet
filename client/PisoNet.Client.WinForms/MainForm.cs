using System.ComponentModel;
using PisoNet.Client.Core;

namespace PisoNet.Client.WinForms;

/// <summary>
/// Main station client window. Displays server-synchronized
/// state only; when disconnected, the last confirmed state is
/// shown and clearly marked as stale.
/// </summary>
internal sealed class MainForm : Form
{
    private readonly ConfigurationStore _configurationStore = new();
    private readonly ICredentialStore _credentialStore = new DpapiCredentialStore();

    private readonly StationStateModel _state = new();
    private readonly SessionCountdown _countdown = new();
    private HeartbeatService? _heartbeatService;
    private StationApiClient? _apiClient;

    private readonly System.Windows.Forms.Timer _refreshTimer = new();

    private StatusDot _connectionDot = new();
    private Label _connectionLabel = new();
    private Label _stationCodeLabel = new();
    private Label _countdownLabel = new();
    private Label _sessionLabel = new();
    private Label _lastSyncLabel = new();
    private Label _messageLabel = new();
    private Panel _lockBanner = new();
    private Label _lockBannerText = new();
    private Button _settingsButton = new();
    private Button _exitButton = new();

    public MainForm()
    {
        BuildLayout();

        _refreshTimer.Interval = 500;
        _refreshTimer.Tick += OnRefreshTick;

        Load += OnLoad;
        FormClosing += OnFormClosing;
    }

    private void BuildLayout()
    {
        Text = "MKY PisoNet Station";
        ClientSize = new Size(480, 400);
        MinimumSize = new Size(480, 400);
        MaximumSize = new Size(480, 400);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = UiTheme.Background;
        Font = UiTheme.StateFont;

        // --- Header: connection state ---
        _connectionDot.Location = new Point(24, 24);
        _connectionDot.DotColor = UiTheme.Muted;

        _connectionLabel = new Label
        {
            Location = new Point(44, 20),
            Size = new Size(300, 20),
            ForeColor = UiTheme.Text,
            Font = UiTheme.TitleFont,
            Text = "Not connected"
        };

        _stationCodeLabel = new Label
        {
            Location = new Point(24, 52),
            Size = new Size(432, 26),
            ForeColor = UiTheme.Muted,
            Font = UiTheme.StationCodeFont,
            Text = "Station: —"
        };

        // --- Card: session countdown ---
        var card = new RoundedPanel
        {
            Location = new Point(24, 92),
            Size = new Size(432, 150),
            Radius = 14
        };

        _countdownLabel = new Label
        {
            Location = new Point(0, 30),
            Size = new Size(432, 52),
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = UiTheme.Text,
            Font = UiTheme.CountdownFont,
            Text = "--:--"
        };

        _sessionLabel = new Label
        {
            Location = new Point(0, 96),
            Size = new Size(432, 22),
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = UiTheme.Muted,
            Text = "No active session"
        };

        _lastSyncLabel = new Label
        {
            Location = new Point(0, 120),
            Size = new Size(432, 20),
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = UiTheme.Muted,
            Font = UiTheme.MessageFont,
            Text = "Awaiting first synchronization"
        };

        card.Controls.Add(_countdownLabel);
        card.Controls.Add(_sessionLabel);
        card.Controls.Add(_lastSyncLabel);

        // --- Lock banner (visible when the server locked the station) ---
        _lockBanner = new Panel
        {
            Location = new Point(24, 256),
            Size = new Size(432, 34),
            BackColor = UiTheme.Bad,
            Visible = false
        };
        _lockBannerText = new Label
        {
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.White,
            Font = UiTheme.TitleFont,
            Text = "LOCKED BY ADMINISTRATOR"
        };
        _lockBanner.Controls.Add(_lockBannerText);

        // --- Status / error message ---
        _messageLabel = new Label
        {
            Location = new Point(24, 304),
            Size = new Size(432, 44),
            ForeColor = UiTheme.Muted,
            Font = UiTheme.MessageFont,
            Text = "Starting…"
        };

        // --- Buttons ---
        _settingsButton = new Button
        {
            Location = new Point(24, 356),
            Size = new Size(140, 30),
            Text = "Settings / Enroll",
            FlatStyle = FlatStyle.Flat,
            BackColor = UiTheme.Card,
            ForeColor = UiTheme.Text
        };
        _settingsButton.FlatAppearance.BorderColor = UiTheme.CardBorder;
        _settingsButton.Click += OnSettingsClick;

        _exitButton = new Button
        {
            Location = new Point(316, 356),
            Size = new Size(140, 30),
            Text = "Exit",
            FlatStyle = FlatStyle.Flat,
            BackColor = UiTheme.Card,
            ForeColor = UiTheme.Text
        };
        _exitButton.FlatAppearance.BorderColor = UiTheme.CardBorder;
        _exitButton.Click += OnExitClick;

        Controls.Add(_connectionDot);
        Controls.Add(_connectionLabel);
        Controls.Add(_stationCodeLabel);
        Controls.Add(card);
        Controls.Add(_lockBanner);
        Controls.Add(_messageLabel);
        Controls.Add(_settingsButton);
        Controls.Add(_exitButton);
    }

    private async void OnLoad(object? sender, EventArgs e)
    {
        var configuration = _configurationStore.Load();
        var hasCredentials = _credentialStore.TryLoad(out var credentials);

        if (configuration is null || !configuration.IsValid || !hasCredentials || credentials is null)
        {
            // First run, or credentials removed: enrollment is
            // an explicit operator action — never silent.
            OpenSettings(firstRun: true);
            return;
        }

        StartClient(configuration, credentials);
    }

    private void StartClient(ClientConfiguration configuration, StationCredentials credentials)
    {
        StopClient();

        _state.StationCode = configuration.StationCode;
        _apiClient = new StationApiClient(configuration);
        _apiClient.SetStationToken(credentials.Token);

        var commandProcessor = new CommandProcessor(_apiClient, _state);
        _heartbeatService = new HeartbeatService(
            configuration, _apiClient, _state, _countdown, commandProcessor);
        _heartbeatService.StateChanged += OnStateChanged;

        _refreshTimer.Start();
        _heartbeatService.Start();
        UpdateUi();
    }

    private async void StopClient()
    {
        _refreshTimer.Stop();
        if (_heartbeatService is not null)
        {
            _heartbeatService.StateChanged -= OnStateChanged;
            await _heartbeatService.StopAsync();
            _heartbeatService = null;
        }

        _apiClient = null;
    }

    private void OnStateChanged()
    {
        // Raised on a thread-pool thread; marshal to the UI thread.
        BeginInvoke(new Action(() =>
        {
            _heartbeatService?.RefreshCountdown();
            UpdateUi();
        }));
    }

    private void OnRefreshTick(object? sender, EventArgs e)
    {
        if (_heartbeatService is null)
        {
            return;
        }

        _heartbeatService.RefreshCountdown();
        UpdateCountdownDisplay();
        UpdateLastSyncDisplay();
    }

    private void UpdateUi()
    {
        // Connection indicator
        _connectionDot.DotColor = _state.Connection switch
        {
            ConnectionState.Connected => UiTheme.Ok,
            ConnectionState.Connecting => UiTheme.Accent,
            ConnectionState.Disconnected => UiTheme.Warn,
            ConnectionState.ServerUnavailable => UiTheme.Bad,
            ConnectionState.AuthenticationFailed => UiTheme.Bad,
            _ => UiTheme.Muted
        };
        _connectionLabel.Text = _state.Connection switch
        {
            ConnectionState.Connected => "Connected",
            ConnectionState.Connecting => "Connecting…",
            ConnectionState.Disconnected => "Connection lost",
            ConnectionState.ServerUnavailable => "Server unavailable",
            ConnectionState.AuthenticationFailed => "Credentials rejected",
            _ => "Not connected"
        };

        _stationCodeLabel.Text = string.IsNullOrEmpty(_state.StationCode)
            ? "Station: —"
            : $"Station: {_state.StationCode}";

        _messageLabel.Text = _state.Message;
        _messageLabel.ForeColor = _state.Connection is
            (ConnectionState.ServerUnavailable or ConnectionState.AuthenticationFailed)
            ? UiTheme.Bad
            : UiTheme.Muted;

        _lockBanner.Visible = _state.IsAdminLocked;

        UpdateCountdownDisplay();
        UpdateLastSyncDisplay();
    }

    private void UpdateCountdownDisplay()
    {
        switch (_state.SessionStatus)
        {
            case SessionStatus.Active:
                _countdownLabel.Text = FormatCountdown(_state.CurrentRemainingSeconds);
                _countdownLabel.ForeColor = _state.IsStale ? UiTheme.Warn : UiTheme.Text;
                _sessionLabel.Text = _state.IsStale
                    ? "Session active (stale — awaiting server)"
                    : "Session active";
                _sessionLabel.ForeColor = _state.IsStale ? UiTheme.Warn : UiTheme.Muted;
                break;

            case SessionStatus.Expired:
                _countdownLabel.Text = "00:00";
                _countdownLabel.ForeColor = UiTheme.Muted;
                _sessionLabel.Text = "Session expired";
                _sessionLabel.ForeColor = UiTheme.Muted;
                break;

            case SessionStatus.Terminated:
                _countdownLabel.Text = "--:--";
                _countdownLabel.ForeColor = UiTheme.Muted;
                _sessionLabel.Text = "Session ended";
                _sessionLabel.ForeColor = UiTheme.Muted;
                break;

            default:
                _countdownLabel.Text = "--:--";
                _countdownLabel.ForeColor = UiTheme.Muted;
                _sessionLabel.Text = "No active session";
                _sessionLabel.ForeColor = UiTheme.Muted;
                break;
        }
    }

    private void UpdateLastSyncDisplay()
    {
        if (_state.LastHeartbeatAtUtc is null)
        {
            _lastSyncLabel.Text = "Awaiting first synchronization";
            return;
        }

        var secondsAgo = (int)(DateTime.UtcNow - _state.LastHeartbeatAtUtc.Value).TotalSeconds;
        var age = secondsAgo < 5
            ? "just now"
            : $"{secondsAgo}s ago";
        _lastSyncLabel.Text = _state.IsStale
            ? $"Last server sync: {age} (stale)"
            : $"Last server sync: {age}";
        _lastSyncLabel.ForeColor = _state.IsStale ? UiTheme.Warn : UiTheme.Muted;
    }

    private static string FormatCountdown(int totalSeconds)
    {
        var clamped = Math.Max(0, totalSeconds);
        return $"{(clamped / 60):00}:{(clamped % 60):00}";
    }

    private void OnSettingsClick(object? sender, EventArgs e) => OpenSettings(firstRun: false);

    private void OnExitClick(object? sender, EventArgs e) => Close();

    private void OpenSettings(bool firstRun)
    {
        using var settings = new SettingsForm(_configurationStore, _credentialStore, firstRun);
        if (settings.ShowDialog(this) == DialogResult.OK && settings.Configuration is { } configuration)
        {
            if (_credentialStore.TryLoad(out var credentials) && credentials is not null)
            {
                StartClient(configuration, credentials);
            }
        }
    }

    private async void OnFormClosing(object? sender, FormClosingEventArgs e)
    {
        _refreshTimer.Stop();
        if (_heartbeatService is not null)
        {
            _heartbeatService.StateChanged -= OnStateChanged;
            await _heartbeatService.StopAsync();
            _heartbeatService = null;
        }
    }
}
