using PisoNet.Client.Core;

namespace PisoNet.Client.WinForms;

/// <summary>
/// Server URL, station identity and enrollment configuration.
/// Enrollment is an explicit operator action: the enrollment
/// secret is typed in here and never persisted.
/// </summary>
internal sealed class SettingsForm : Form
{
    private readonly ConfigurationStore _configurationStore;
    private readonly ICredentialStore _credentialStore;

    private TextBox _serverUrlBox = new();
    private TextBox _stationCodeBox = new();
    private TextBox _displayNameBox = new();
    private TextBox _enrollmentSecretBox = new();
    private Label _errorLabel = new();
    private Label _statusLabel = new();

    public ClientConfiguration? Configuration { get; private set; }

    public SettingsForm(
        ConfigurationStore configurationStore,
        ICredentialStore credentialStore,
        bool firstRun)
    {
        _configurationStore = configurationStore;
        _credentialStore = credentialStore;
        BuildLayout(firstRun);
        LoadExistingConfiguration();
    }

    private void BuildLayout(bool firstRun)
    {
        Text = firstRun ? "Station Setup" : "Settings / Enroll";
        ClientSize = new Size(440, 420);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterParent;
        BackColor = UiTheme.Background;
        Font = UiTheme.StateFont;

        var y = 18;

        Controls.Add(CreateLabel("Server URL (http://…)", 20, y));
        _serverUrlBox = CreateTextBox(20, y += 24, "http://127.0.0.1:8000");
        y += 34;

        Controls.Add(CreateLabel("Station code", 20, y));
        _stationCodeBox = CreateTextBox(20, y += 24, "PC-01");
        y += 34;

        Controls.Add(CreateLabel("Display name (optional)", 20, y));
        _displayNameBox = CreateTextBox(20, y += 24, "");
        y += 34;

        Controls.Add(CreateLabel("Enrollment secret (from the operator)", 20, y));
        _enrollmentSecretBox = CreateTextBox(20, y += 24, "");
        _enrollmentSecretBox.UseSystemPasswordChar = true;
        y += 40;

        _errorLabel = new Label
        {
            Location = new Point(20, y),
            Size = new Size(400, 40),
            ForeColor = UiTheme.Bad,
            Font = UiTheme.MessageFont,
            Text = ""
        };
        Controls.Add(_errorLabel);
        y += 44;

        _statusLabel = new Label
        {
            Location = new Point(20, y),
            Size = new Size(400, 24),
            ForeColor = UiTheme.Ok,
            Font = UiTheme.MessageFont,
            Text = ""
        };
        Controls.Add(_statusLabel);
        y += 32;

        var saveButton = new Button
        {
            Location = new Point(20, y),
            Size = new Size(190, 30),
            Text = "Save configuration",
            FlatStyle = FlatStyle.Flat,
            BackColor = UiTheme.Card,
            ForeColor = UiTheme.Text
        };
        saveButton.FlatAppearance.BorderColor = UiTheme.CardBorder;
        saveButton.Click += OnSaveClick;
        Controls.Add(saveButton);

        var enrollButton = new Button
        {
            Location = new Point(230, y),
            Size = new Size(190, 30),
            Text = "Enroll station",
            FlatStyle = FlatStyle.Flat,
            BackColor = UiTheme.Accent,
            ForeColor = Color.White
        };
        enrollButton.FlatAppearance.BorderColor = UiTheme.Accent;
        enrollButton.Click += OnEnrollClick;
        Controls.Add(enrollButton);
        y += 42;

        var resetButton = new Button
        {
            Location = new Point(20, y),
            Size = new Size(190, 30),
            Text = "Remove stored credentials",
            FlatStyle = FlatStyle.Flat,
            BackColor = UiTheme.Card,
            ForeColor = UiTheme.Text
        };
        resetButton.FlatAppearance.BorderColor = UiTheme.CardBorder;
        resetButton.Click += OnResetClick;
        Controls.Add(resetButton);

        var closeButton = new Button
        {
            Location = new Point(230, y),
            Size = new Size(190, 30),
            Text = "Close",
            FlatStyle = FlatStyle.Flat,
            BackColor = UiTheme.Card,
            ForeColor = UiTheme.Text
        };
        closeButton.FlatAppearance.BorderColor = UiTheme.CardBorder;
        closeButton.Click += (_, _) => Close();
        Controls.Add(closeButton);
    }

    private static Label CreateLabel(string text, int x, int y) => new()
    {
        Location = new Point(x, y),
        Size = new Size(400, 18),
        ForeColor = UiTheme.Muted,
        Font = UiTheme.MessageFont,
        Text = text
    };

    private static TextBox CreateTextBox(int x, int y, string text) => new()
    {
        Location = new Point(x, y),
        Size = new Size(400, 26),
        BackColor = UiTheme.Card,
        ForeColor = UiTheme.Text,
        BorderStyle = BorderStyle.FixedSingle,
        Text = text
    };

    private void LoadExistingConfiguration()
    {
        var configuration = _configurationStore.Load();
        if (configuration is null)
        {
            return;
        }

        _serverUrlBox.Text = configuration.ServerUrl;
        _stationCodeBox.Text = configuration.StationCode;
        _displayNameBox.Text = configuration.DisplayName ?? "";
    }

    private ClientConfiguration? ReadConfiguration()
    {
        return new ClientConfiguration
        {
            ServerUrl = _serverUrlBox.Text.Trim(),
            StationCode = _stationCodeBox.Text.Trim(),
            DisplayName = string.IsNullOrWhiteSpace(_displayNameBox.Text)
                ? null
                : _displayNameBox.Text.Trim(),
        };
    }

    private void OnSaveClick(object? sender, EventArgs e)
    {
        var configuration = ReadConfiguration();
        if (configuration is null)
        {
            return;
        }

        var errors = configuration.Validate();
        if (errors.Count > 0)
        {
            ShowErrors(errors);
            return;
        }

        _configurationStore.Save(configuration);
        _statusLabel.Text = "Configuration saved.";
        _errorLabel.Text = "";
    }

    private async void OnEnrollClick(object? sender, EventArgs e)
    {
        _errorLabel.Text = "";
        _statusLabel.Text = "";

        var configuration = ReadConfiguration();
        if (configuration is null)
        {
            return;
        }

        var errors = configuration.Validate();
        var secret = _enrollmentSecretBox.Text;
        if (string.IsNullOrWhiteSpace(secret))
        {
            errors = errors.Append("Enrollment secret is required.").ToList();
        }
        if (errors.Count > 0)
        {
            ShowErrors(errors);
            return;
        }

        // Enroll with a bounded timeout; never silently retry
        // on failure.
        using var apiClient = new StationApiClient(configuration);
        try
        {
            var result = await apiClient.RegisterAsync(secret);
            // Persist configuration and the issued credential.
            _configurationStore.Save(configuration);
            _credentialStore.Save(new StationCredentials(
                result.StationCode, result.Token));
            Configuration = configuration;
            _statusLabel.Text =
                $"Station {result.StationCode} enrolled. Starting…";
            _enrollmentSecretBox.Text = "";
            // Close shortly after success so the main form starts.
            await Task.Delay(600);
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (StationAuthenticationException)
        {
            // Not expected for enrollment, but handled explicitly.
            ShowErrors(["The server rejected this request."]);
        }
        catch (EnrollmentRejectedException)
        {
            ShowErrors([
                "Enrollment rejected: the enrollment secret is incorrect. " +
                "Ask the operator for the current secret from the dashboard."]);
        }
        catch (DuplicateStationException)
        {
            ShowErrors([
                $"Station code '{configuration.StationCode}' is already enrolled. " +
                "Choose a different station code, or use Rotate credential on the " +
                "dashboard for this station."]);
        }
        catch (ProtocolVersionMismatchException)
        {
            ShowErrors([
                "The server rejected the client protocol. " +
                "Update the client to a version compatible with this server."]);
        }
        catch (HttpRequestException exception)
        {
            ShowErrors([
                $"Could not reach the server: {exception.Message}",
                "Check the server URL and that the PisoNet server is running."]);
        }
        catch (TaskCanceledException)
        {
            ShowErrors([
                "The server did not respond in time. " +
                "Check the server URL and network, then try again."]);
        }
    }

    private void OnResetClick(object? sender, EventArgs e)
    {
        _credentialStore.Clear();
        _statusLabel.Text = "Stored credentials removed. Re-enrollment required.";
        _errorLabel.Text = "";
    }

    private void ShowErrors(IReadOnlyList<string> errors)
    {
        _errorLabel.Text = string.Join(Environment.NewLine, errors);
        _statusLabel.Text = "";
    }
}
