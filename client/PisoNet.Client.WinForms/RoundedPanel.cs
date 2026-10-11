using System.ComponentModel;

namespace PisoNet.Client.WinForms;

/// <summary>Panel with restrained rounded corners and a thin border.</summary>
internal sealed class RoundedPanel : Panel
{
    private int _radius = 12;

    [Browsable(false)]
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public int Radius
    {
        get => _radius;
        set
        {
            _radius = value;
            Invalidate();
        }
    }

    public RoundedPanel()
    {
        BackColor = UiTheme.Card;
        DoubleBuffered = true;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var graphics = e.Graphics;
        graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var path = CreateRoundedRectangle(ClientRectangle, _radius);
        using var brush = new SolidBrush(BackColor);
        graphics.FillPath(brush, path);
        using var pen = new Pen(UiTheme.CardBorder);
        graphics.DrawPath(pen, path);
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
        // Painted in OnPaint instead.
    }

    private static System.Drawing.Drawing2D.GraphicsPath CreateRoundedRectangle(
        Rectangle bounds,
        int radius)
    {
        var path = new System.Drawing.Drawing2D.GraphicsPath();
        var diameter = radius * 2;
        path.AddArc(bounds.X, bounds.Y, diameter, diameter, 180, 90);
        path.AddArc(bounds.Right - diameter, bounds.Y, diameter, diameter, 270, 90);
        path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
        path.AddArc(bounds.X, bounds.Bottom - diameter, diameter, diameter, 90, 90);
        path.CloseFigure();
        return path;
    }
}
