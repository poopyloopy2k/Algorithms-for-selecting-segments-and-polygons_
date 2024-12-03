from flask import Flask, request, render_template_string
import plotly.graph_objects as go
import plotly.io as pio

app = Flask(__name__)

def parse_input_data(data):
    if not data:
        raise ValueError("No input data provided.")

    n = int(data[0])
    segments = []
    for i in range(1, n + 1):
        line = data[i].strip()
        if not line:
            raise ValueError(f"Missing segment data at line {i + 1}.")
        coords = list(map(float, line.split()))
        if len(coords) != 4:
            raise ValueError(f"Invalid segment data at line {i + 1}. Expected 4 coordinates.")
        x1, y1, x2, y2 = coords
        segments.append(((x1, y1), (x2, y2)))

    if len(data) < n + 2:
        raise ValueError("Missing clipping window data.")

    clipping_window = list(map(float, data[n + 1].split()))
    if len(clipping_window) != 4:
        raise ValueError("Invalid clipping window data. Expected 4 coordinates.")

    polygon = []
    if len(data) > n + 2:
        if data[n + 2].startswith("P"):
            vertices = list(map(float, data[n + 2][1:].split()))
            if len(vertices) < 2:
                raise ValueError("Invalid polygon data. At least one vertex required.")
            if len(vertices) % 2 != 0:
                raise ValueError("Invalid polygon data. Coordinates must be in pairs.")
            polygon = [(vertices[i], vertices[i + 1]) for i in range(0, len(vertices), 2)]
        else:
            raise ValueError("Invalid data format. Expected polygon data starting with 'P'.")

    return segments, clipping_window, polygon

def is_inside(point, clipping_window):
    Xmin, Ymin, Xmax, Ymax = clipping_window
    x, y = point
    return Xmin <= x <= Xmax and Ymin <= y <= Ymax

def cohen_sutherland_clip(segment, clipping_window):
    Xmin, Ymin, Xmax, Ymax = clipping_window
    p1, p2 = segment
    x1, y1 = p1
    x2, y2 = p2

    def compute_t(boundary_value, start, delta):
        if delta == 0:
            return None
        t = (boundary_value - start) / delta
        if 0 <= t <= 1:
            return t
        else:
            return None

    t_values = []

    # Left boundary
    t_left = compute_t(Xmin, x1, x2 - x1)
    if t_left is not None:
        if is_inside((x1, y1), clipping_window):
            t_values.append(t_left)
        else:
            t_values.append(t_left)

    # Right boundary
    t_right = compute_t(Xmax, x1, x2 - x1)
    if t_right is not None:
        if is_inside((x1, y1), clipping_window):
            t_values.append(t_right)
        else:
            t_values.append(t_right)

    # Bottom boundary
    t_bottom = compute_t(Ymin, y1, y2 - y1)
    if t_bottom is not None:
        if is_inside((x1, y1), clipping_window):
            t_values.append(t_bottom)
        else:
            t_values.append(t_bottom)

    # Top boundary
    t_top = compute_t(Ymax, y1, y2 - y1)
    if t_top is not None:
        if is_inside((x1, y1), clipping_window):
            t_values.append(t_top)
        else:
            t_values.append(t_top)

    t_values = sorted(t_values)

    if is_inside(p1, clipping_window) and is_inside(p2, clipping_window):
        return (p1, p2)
    elif is_inside(p1, clipping_window):
        t = t_values[0]
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return (p1, (x, y))
    elif is_inside(p2, clipping_window):
        t = t_values[-1]
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return ((x, y), p2)
    elif len(t_values) >= 2:
        t1 = t_values[0]
        t2 = t_values[1]
        x1_clipped = x1 + t1 * (x2 - x1)
        y1_clipped = y1 + t1 * (y2 - y1)
        x2_clipped = x1 + t2 * (x2 - x1)
        y2_clipped = y1 + t2 * (y2 - y1)
        return ((x1_clipped, y1_clipped), (x2_clipped, y2_clipped))
    else:
        return None

def sutherland_hodgman_clip(polygon, clipping_window):
    def clip_edge(polygon, edge):
        Xmin, Ymin, Xmax, Ymax = clipping_window
        new_polygon = []
        p0 = polygon[-1]
        for p1 in polygon:
            if edge == 'left':
                accept_p1 = p1[0] >= Xmin
                accept_p0 = p0[0] >= Xmin
                boundary = Xmin
                axis = 0
            elif edge == 'bottom':
                accept_p1 = p1[1] >= Ymin
                accept_p0 = p0[1] >= Ymin
                boundary = Ymin
                axis = 1
            elif edge == 'right':
                accept_p1 = p1[0] <= Xmax
                accept_p0 = p0[0] <= Xmax
                boundary = Xmax
                axis = 0
            elif edge == 'top':
                accept_p1 = p1[1] <= Ymax
                accept_p0 = p0[1] <= Ymax
                boundary = Ymax
                axis = 1

            if accept_p1:
                if not accept_p0:
                    t = (boundary - p0[axis]) / (p1[axis] - p0[axis])
                    if p1[axis] - p0[axis] == 0:
                        continue
                    x = p0[0] + t * (p1[0] - p0[0])
                    y = p0[1] + t * (p1[1] - p0[1])
                    new_polygon.append((x, y))
                new_polygon.append(p1)
            else:
                if accept_p0:
                    t = (boundary - p0[axis]) / (p1[axis] - p0[axis])
                    if p1[axis] - p0[axis] == 0:
                        continue
                    x = p0[0] + t * (p1[0] - p0[0])
                    y = p0[1] + t * (p1[1] - p0[1])
                    new_polygon.append((x, y))
            p0 = p1
        return new_polygon

    # Clip polygon against each edge in order: left, bottom, right, top
    for edge in ['left', 'bottom', 'right', 'top']:
        polygon = clip_edge(polygon, edge)
    return polygon

def generate_line_plot(clipping_window, original_segments, clipped_segments):
    fig = go.Figure()

    # Plot clipping window
    fig.add_trace(go.Scatter(
        x=[clipping_window[0], clipping_window[2], clipping_window[2], clipping_window[0], clipping_window[0]],
        y=[clipping_window[1], clipping_window[1], clipping_window[3], clipping_window[3], clipping_window[1]],
        mode='lines',
        name='Clipping Window',
        line=dict(color='red')
    ))

    # Plot original segments
    for seg in original_segments:
        fig.add_trace(go.Scatter(
            x=[seg[0][0], seg[1][0]],
            y=[seg[0][1], seg[1][1]],
            mode='lines',
            name='Original Segment',
            line=dict(color='blue', dash='dash')
        ))

    # Plot clipped segments that are entirely within the window
    for seg in clipped_segments:
        if seg:
            fig.add_trace(go.Scatter(
                x=[seg[0][0], seg[1][0]],
                y=[seg[0][1], seg[1][1]],
                mode='lines',
                name='Clipped Segment',
                line=dict(color='green')
            ))

    # Set axis limits
    Xmin, Ymin, Xmax, Ymax = clipping_window
    fig.update_layout(
        xaxis=dict(range=[Xmin - 1, Xmax + 1]),
        yaxis=dict(range=[Ymin - 1, Ymax + 1]),
        title='Cohen-Sutherland Clipping Algorithm',
        showlegend=True
    )

    return fig

def generate_polygon_plot(clipping_window, original_polygon, clipped_polygon):
    fig = go.Figure()

    # Plot clipping window
    fig.add_trace(go.Scatter(
        x=[clipping_window[0], clipping_window[2], clipping_window[2], clipping_window[0], clipping_window[0]],
        y=[clipping_window[1], clipping_window[1], clipping_window[3], clipping_window[3], clipping_window[1]],
        mode='lines',
        name='Clipping Window',
        line=dict(color='red')
    ))

    # Plot original polygon
    if original_polygon:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in original_polygon] + [original_polygon[0][0]],
            y=[p[1] for p in original_polygon] + [original_polygon[0][1]],
            mode='lines',
            name='Original Polygon',
            line=dict(color='purple', dash='dash')
        ))

    # Plot clipped polygon
    if clipped_polygon:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in clipped_polygon] + [clipped_polygon[0][0]],
            y=[p[1] for p in clipped_polygon] + [clipped_polygon[0][1]],
            mode='lines',
            name='Clipped Polygon',
            line=dict(color='orange')
        ))

    # Set axis limits
    Xmin, Ymin, Xmax, Ymax = clipping_window
    fig.update_layout(
        xaxis=dict(range=[Xmin - 1, Xmax + 1]),
        yaxis=dict(range=[Ymin - 1, Ymax + 1]),
        title='Sutherland-Hodgman Clipping Algorithm',
        showlegend=True
    )

    return fig

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        input_method = request.form.get('input_method')
        if input_method == 'file':
            file = request.files.get('file')
            if not file:
                return "No file uploaded", 400
            data = file.read().decode('utf-8').splitlines()
        elif input_method == 'manual':
            text_input = request.form.get('text_input')
            if not text_input:
                return "No input data provided", 400
            data = text_input.splitlines()
        else:
            return "Invalid input method", 400

        try:
            segments, clipping_window, polygon = parse_input_data(data)
        except Exception as e:
            return f"Error parsing input data: {str(e)}", 400

        # Cohen-Sutherland Clipping
        clipped_segments = []
        for seg in segments:
            clipped_seg = cohen_sutherland_clip(seg, clipping_window)
            clipped_segments.append(clipped_seg)

        # Sutherland-Hodgman Clipping
        if polygon:
            clipped_polygon = sutherland_hodgman_clip(polygon, clipping_window)
        else:
            clipped_polygon = []

        # Generate plots
        line_plot = generate_line_plot(clipping_window, segments, clipped_segments)
        polygon_plot = generate_polygon_plot(clipping_window, polygon, clipped_polygon)

        # Convert plots to HTML
        line_plot_html = pio.to_html(line_plot, full_html=False)
        polygon_plot_html = pio.to_html(polygon_plot, full_html=False)

        return render_template_string('''
            <!DOCTYPE html>
            <html>
                <head>
                    <title>Clipping Algorithms Visualization</title>
                    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
                </head>
                <body>
                    <h1>Cohen-Sutherland Clipping Algorithm</h1>
                    {{ line_plot|safe }}
                    <h1>Sutherland-Hodgman Clipping Algorithm</h1>
                    {{ polygon_plot|safe }}
                </body>
            </html>
        ''', line_plot=line_plot_html, polygon_plot=polygon_plot_html)

    return '''
    <form method="post" enctype="multipart/form-data">
        <input type="radio" name="input_method" value="file" checked> Input via file
        <input type="radio" name="input_method" value="manual"> Input manually
        <br>
        <div id="file-input">
            <input type="file" name="file">
        </div>
        <div id="manual-input" style="display:none;">
            <textarea name="text_input" rows="15" cols="50">
-- Sample Input Format --
Number of segments
x1 y1 x2 y2
...
Clipping window Xmin Ymin Xmax Ymax
P x1 y1 x2 y2 x3 y3 ...
</textarea>
        </div>
        <input type="submit" value="Submit">
    </form>
    <script>
        document.querySelector('input[type=radio][name=input_method]').addEventListener('change', function() {
            if (this.value === 'file') {
                document.getElementById('file-input').style.display = 'block';
                document.getElementById('manual-input').style.display = 'none';
            } else if (this.value === 'manual') {
                document.getElementById('file-input').style.display = 'none';
                document.getElementById('manual-input').style.display = 'block';
            }
        });
    </script>
    '''

if __name__ == '__main__':
    app.run(debug=True)