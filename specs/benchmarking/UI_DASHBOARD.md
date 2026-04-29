# Benchmarking UI Dashboard Specification

**Version:** 1.0
**Status:** Production-Ready
**Last Updated:** 2025-12-28
**Parent:** [REQUIREMENTS.md](../REQUIREMENTS.md)

## Executive Summary

This specification defines the web-based UI dashboard for visualizing, querying, and analyzing benchmark statistics. The dashboard provides actionable insights for model selection, performance optimization, and capacity planning.

## Table of Contents

1. [Dashboard Requirements](#dashboard-requirements)
2. [User Personas](#user-personas)
3. [Feature Specifications](#feature-specifications)
4. [UI Components](#ui-components)
5. [Data Visualization](#data-visualization)
6. [Quality Dimensions](#quality-dimensions)
7. [Acceptance Criteria](#acceptance-criteria)
8. [Implementation Guidance](#implementation-guidance)

---

## Dashboard Requirements

### DASH-001: Web-Based Interface
**Priority:** P0 (Critical)

The dashboard MUST be accessible via web browser without CLI knowledge.

**Technical Requirements:**
- Web framework: Flask or FastAPI
- Port: 8080 (configurable)
- Authentication: Optional (basic auth for production)
- Browser support: Chrome 90+, Firefox 88+, Safari 14+

**Launch Command:**
```bash
python -m src.benchmarking.cli dashboard --port 8080
```

**Expected Output:**
```
Benchmark Dashboard Starting...
└─ Database: data/benchmarks/benchmarks.db (720 runs, 36 languages, 10 models)
└─ Server: http://localhost:8080
└─ Press Ctrl+C to stop
```

### DASH-002: Real-Time Query Interface
**Priority:** P0 (Critical)

Users MUST be able to query benchmark data interactively without SQL knowledge.

**Query Builder Interface:**
```
┌─────────────────────────────────────────┐
│ Benchmark Query Builder                 │
├─────────────────────────────────────────┤
│ Model:      [All Models ▼]              │
│ Language:   [All Languages ▼]           │
│ Device:     [CPU] [GPU] [Both]          │
│ Cache:      [Cached] [Uncached] [Mixed] │
│ Date Range: [Last 30 Days ▼]            │
│                                          │
│ [Run Query] [Reset] [Export CSV]        │
└─────────────────────────────────────────┘
```

**Query Response Time:**
- Simple queries (single model/language): <100ms
- Complex queries (aggregations, joins): <500ms
- Timeout: 5 seconds (user-facing error message)

### DASH-003: Comparison Views
**Priority:** P1 (High)

Users MUST be able to compare performance across:
- Models (for same language/device)
- Languages (for same model/device)
- Devices (CPU vs GPU for same model/language)

**Comparison Table Example:**

| Model | Language | Device | Throughput (seg/sec) | Latency P95 (ms) | Memory (MB) | BLEU Score |
|-------|----------|--------|----------------------|------------------|-------------|------------|
| m2m100_418m | fr | CPU | 12.5 | 180 | 1,800 | 34.2 |
| m2m100_418m | fr | GPU | 48.3 | 42 | 2,100 (VRAM: 1,400) | 34.2 |
| nllb_200_600m | fr | CPU | 8.7 | 260 | 2,400 | 36.8 |
| nllb_200_600m | fr | GPU | 38.1 | 58 | 2,800 (VRAM: 1,900) | 36.8 |

**Sort and Filter:**
- Sort by any column (ascending/descending)
- Multi-column filtering (e.g., "Show GPU runs with BLEU > 35")

### DASH-004: Interactive Charts
**Priority:** P1 (High)

Dashboard MUST include interactive visualizations using Plotly or Chart.js.

**Required Chart Types:**
1. Throughput bar chart (models × languages)
2. Latency distribution (box plot or violin plot)
3. Memory usage scatter plot (RAM vs VRAM)
4. BLEU score heatmap (models × languages)
5. CPU vs GPU speedup chart
6. Cache impact chart (cached vs uncached throughput)

**Interactivity:**
- Hover tooltips with detailed metrics
- Click to drill down (e.g., click language to see all models)
- Zoom and pan for large datasets
- Legend toggle (show/hide series)

### DASH-005: Export Capabilities
**Priority:** P1 (High)

Users MUST be able to export benchmark results in multiple formats.

**Supported Formats:**
- CSV (for Excel, data analysis)
- JSON (for programmatic access)
- PNG (chart images for reports)
- PDF (full dashboard snapshot)

**Export Button:**
```
[Export ▼]
  ├─ CSV (Current View)
  ├─ JSON (All Data)
  ├─ PNG (Chart Image)
  └─ PDF (Full Report)
```

**File Naming Convention:**
```
benchmark_export_{model}_{language}_{device}_{timestamp}.csv
benchmark_export_all_{timestamp}.json
```

### DASH-006: Recommendation Engine
**Priority:** P2 (Medium)

Dashboard SHOULD provide model selection recommendations based on constraints.

**Recommendation Form:**
```
┌─────────────────────────────────────────┐
│ Model Recommendation Engine              │
├─────────────────────────────────────────┤
│ Target Language:    [French (fr) ▼]     │
│ Priority:           [Speed ▼]            │
│                     (Speed, Quality, Memory)│
│ Device Available:   [CPU] [GPU]          │
│ Max Memory (MB):    [2000]               │
│ Min BLEU Score:     [30.0]               │
│                                          │
│ [Get Recommendation]                     │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Recommended Model: m2m100_418m_ct2_int8  │
├─────────────────────────────────────────┤
│ Throughput:    25.3 seg/sec              │
│ Latency P95:   95 ms                     │
│ Memory:        1,200 MB                  │
│ BLEU Score:    33.8                      │
│ Speedup:       2.0x vs. default          │
│                                          │
│ [Use This Model] [See Alternatives]     │
└─────────────────────────────────────────┘
```

**Recommendation Algorithm:**
```python
def recommend_model(language, priority, device, max_memory, min_bleu):
    # Filter models by constraints
    candidates = db.query("""
        SELECT model_id, throughput, memory, bleu_score
        FROM benchmark_runs
        WHERE language = ?
          AND device = ?
          AND memory <= ?
          AND bleu_score >= ?
    """, (language, device, max_memory, min_bleu))

    # Sort by priority
    if priority == "speed":
        candidates.sort(key=lambda x: x.throughput, reverse=True)
    elif priority == "quality":
        candidates.sort(key=lambda x: x.bleu_score, reverse=True)
    elif priority == "memory":
        candidates.sort(key=lambda x: x.memory)

    return candidates[0]  # Top candidate
```

---

## User Personas

### Persona 1: Translation Operator
**Goal:** Select the best model for a specific language and device.

**Needs:**
- Quick comparison of model performance
- Clear recommendation for most common use cases
- Export results to share with team

**Primary Views:**
- Comparison table (models for single language)
- Recommendation engine
- CSV export

### Persona 2: Performance Engineer
**Goal:** Optimize resource usage and identify bottlenecks.

**Needs:**
- Detailed metrics (latency percentiles, memory breakdown)
- CPU vs GPU comparison
- Cache impact analysis

**Primary Views:**
- Interactive charts (latency distribution, memory scatter)
- Cache scenario comparison
- JSON export for scripting

### Persona 3: Product Manager
**Goal:** Understand translation quality across languages.

**Needs:**
- BLEU score comparisons
- Language coverage verification
- High-level dashboard summaries

**Primary Views:**
- BLEU score heatmap
- Language coverage table
- PDF export for stakeholder reports

### Persona 4: System Administrator
**Goal:** Monitor benchmark system health and resource usage.

**Needs:**
- Benchmark run history
- Error rate tracking
- Database size monitoring

**Primary Views:**
- System status dashboard
- Error logs
- Database statistics

---

## Feature Specifications

### Feature 1: Model Comparison View

**User Story:**
> As a translation operator, I want to compare all models for French translation so that I can choose the fastest model for CPU deployment.

**Interface:**
```
┌────────────────────────────────────────────────────────────────┐
│ Model Comparison: French (fr) - CPU                            │
├────────────────────────────────────────────────────────────────┤
│ Model               │ Throughput │ Latency P95 │ Memory │ BLEU │
│                     │ (seg/sec)  │    (ms)     │  (MB)  │      │
├─────────────────────┼────────────┼─────────────┼────────┼──────┤
│ m2m100_418m_ct2_int8│   25.3 🥇  │      95     │ 1,200  │ 33.8 │
│ m2m100_418m_ct2     │   18.7 🥈  │     120     │ 1,800  │ 34.2 │
│ m2m100_418m         │   12.5 🥉  │     180     │ 2,100  │ 34.2 │
│ nllb_200_600m_ct2   │   14.2     │     155     │ 2,400  │ 36.8 │
│ nllb_200_600m       │    8.7     │     260     │ 3,200  │ 36.8 │
└─────────────────────┴────────────┴─────────────┴────────┴──────┘

[Sort by Throughput ▼] [Show GPU Results] [Export CSV]
```

**Acceptance Criteria:**
- [ ] All models for selected language visible
- [ ] Fastest model highlighted (medal emoji)
- [ ] Sorting by any column supported
- [ ] Export to CSV functional

### Feature 2: Language Coverage Heatmap

**User Story:**
> As a product manager, I want to see BLEU scores for all languages at a glance so that I can identify languages needing quality improvement.

**Visualization:**
```
BLEU Score Heatmap (Model: m2m100_418m, Device: GPU)

        ar  bg  ca  cs  da  de  el  es  fa  fi  fr  ...
Model
m2m100  28  31  35  33  34  36  30  37  26  32  34  ...
nllb    30  33  37  35  36  38  32  39  28  34  37  ...

Color Scale: 20 (red) ────────► 40 (green)
```

**Implementation:**
- Plotly Heatmap or Seaborn
- Color gradient: Low BLEU (red) → High BLEU (green)
- Hover tooltip: "Model: m2m100, Language: fr, BLEU: 34.2"

### Feature 3: CPU vs GPU Speedup Chart

**User Story:**
> As a performance engineer, I want to see GPU speedup for each model so that I can justify GPU infrastructure costs.

**Chart:**
```
GPU Speedup Factor (Throughput GPU / Throughput CPU)

   6x ┤                     ●
      │
   5x ┤              ●
      │
   4x ┤     ●        ●      ●
      │
   3x ┤     ●   ●
      │
   2x ┤ ●
      │
   1x ┼──────────────────────────────────
      m2m  m2m  nllb nllb opus opus small
      418m 1.2b 600m 1.3b en_fr en_es 100

[Show All Languages ▼] [Export PNG]
```

**Calculation:**
```python
speedup = throughput_gpu / throughput_cpu
```

**Acceptance Criteria:**
- [ ] Speedup >1x indicates GPU advantage
- [ ] Models with no GPU support show N/A
- [ ] Hover shows absolute throughput values

### Feature 4: Cache Impact Comparison

**User Story:**
> As a performance engineer, I want to see throughput difference between cached and uncached scenarios so that I can optimize TM usage.

**Bar Chart:**
```
Cache Impact (Model: m2m100_418m, Language: fr, Device: CPU)

Throughput (seg/sec)
   ┤
900┤     ████████████████████████  Cached: 850 seg/sec
   ┤
600┤
   ┤
300┤
   ┤
  0┤ ███  Uncached: 12.5 seg/sec
   └────────────────────────────────────────────
         Uncached        Cached

Cache Speedup: 68x
Cache Hit Rate: 100%
```

**Acceptance Criteria:**
- [ ] Shows both cached and uncached throughput
- [ ] Calculates speedup factor
- [ ] Displays cache hit rate

### Feature 5: Latency Distribution

**User Story:**
> As a system administrator, I want to see latency distribution to identify outliers and tail latency.

**Box Plot:**
```
Translation Latency Distribution (Language: fr, Device: GPU)

Latency (ms)
   ┤
400┤                                 ○ Outlier
   ┤
300┤              ┌──┐
   ┤              │  │
200┤         ┌────┤  ├────┐
   ┤         │    │  │    │
100┤    ─────┤    └──┘    ├─────
   ┤         │            │
  0┤         └────────────┘
   └──────────────────────────────
     m2m100  nllb   opus   small
     418m    600m   en_fr  100

P50 (median): 120ms
P95: 180ms
P99: 220ms
Max: 380ms (outlier)
```

**Implementation:**
- Plotly Box Plot
- Show P50, P95, P99 lines
- Highlight outliers (>3 std dev)

---

## UI Components

### Component 1: Navigation Bar

```html
<nav class="navbar">
  <div class="logo">📊 Hugo Translator Benchmarks</div>
  <ul class="nav-links">
    <li><a href="/">Dashboard</a></li>
    <li><a href="/comparison">Model Comparison</a></li>
    <li><a href="/heatmap">Language Coverage</a></li>
    <li><a href="/recommendation">Recommendation</a></li>
    <li><a href="/export">Export</a></li>
    <li><a href="/about">About</a></li>
  </ul>
</nav>
```

### Component 2: Query Builder

```html
<form id="query-builder" class="card">
  <h2>Benchmark Query Builder</h2>

  <div class="form-group">
    <label for="model">Model:</label>
    <select id="model" name="model">
      <option value="all">All Models</option>
      <option value="m2m100_418m">M2M100 418M</option>
      <!-- ... -->
    </select>
  </div>

  <div class="form-group">
    <label for="language">Language:</label>
    <select id="language" name="language">
      <option value="all">All Languages</option>
      <option value="fr">French (fr)</option>
      <!-- ... -->
    </select>
  </div>

  <div class="form-group">
    <label>Device:</label>
    <input type="checkbox" id="cpu" name="device" value="cpu" checked>
    <label for="cpu">CPU</label>
    <input type="checkbox" id="gpu" name="device" value="cuda" checked>
    <label for="gpu">GPU</label>
  </div>

  <button type="submit" class="btn-primary">Run Query</button>
  <button type="reset" class="btn-secondary">Reset</button>
</form>
```

### Component 3: Results Table

```html
<table id="results-table" class="data-table">
  <thead>
    <tr>
      <th data-sort="model_id">Model ↕</th>
      <th data-sort="language">Language ↕</th>
      <th data-sort="device">Device ↕</th>
      <th data-sort="throughput">Throughput (seg/sec) ↕</th>
      <th data-sort="latency_p95">Latency P95 (ms) ↕</th>
      <th data-sort="memory">Memory (MB) ↕</th>
      <th data-sort="bleu_score">BLEU ↕</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody id="results-body">
    <!-- Dynamically populated via JavaScript -->
  </tbody>
</table>

<div class="table-footer">
  <span id="row-count">Showing 10 of 720 results</span>
  <div class="pagination">
    <button id="prev-page">← Previous</button>
    <span id="page-info">Page 1 of 72</span>
    <button id="next-page">Next →</button>
  </div>
</div>
```

### Component 4: Chart Container

```html
<div class="chart-container card">
  <div class="chart-header">
    <h3>Throughput Comparison</h3>
    <div class="chart-controls">
      <button class="btn-icon" title="Download PNG">📥</button>
      <button class="btn-icon" title="Fullscreen">⛶</button>
    </div>
  </div>
  <div id="chart-throughput" class="chart"></div>
</div>

<script>
  // Plotly chart initialization
  const data = [{
    x: ['m2m100_418m', 'nllb_200_600m', 'opus_en_fr'],
    y: [12.5, 8.7, 22.3],
    type: 'bar',
    name: 'CPU'
  }, {
    x: ['m2m100_418m', 'nllb_200_600m', 'opus_en_fr'],
    y: [48.3, 38.1, 85.7],
    type: 'bar',
    name: 'GPU'
  }];

  const layout = {
    title: 'Throughput: CPU vs GPU (Language: fr)',
    xaxis: { title: 'Model' },
    yaxis: { title: 'Throughput (segments/sec)' },
    barmode: 'group'
  };

  Plotly.newPlot('chart-throughput', data, layout);
</script>
```

### Component 5: Export Modal

```html
<div id="export-modal" class="modal">
  <div class="modal-content">
    <h2>Export Benchmark Data</h2>

    <div class="export-options">
      <label>
        <input type="radio" name="export-format" value="csv" checked>
        CSV (Current View)
      </label>
      <label>
        <input type="radio" name="export-format" value="json">
        JSON (All Data)
      </label>
      <label>
        <input type="radio" name="export-format" value="png">
        PNG (Chart Image)
      </label>
    </div>

    <div class="export-preview">
      <strong>Preview:</strong>
      <pre id="export-preview-text">
model_id,language,device,throughput,latency_p95,memory,bleu_score
m2m100_418m,fr,cpu,12.5,180,1800,34.2
m2m100_418m,fr,cuda,48.3,42,2100,34.2
...
      </pre>
    </div>

    <div class="modal-actions">
      <button id="export-download" class="btn-primary">Download</button>
      <button id="export-cancel" class="btn-secondary">Cancel</button>
    </div>
  </div>
</div>
```

---

## Data Visualization

### Chart 1: Throughput Bar Chart

**Purpose:** Compare model throughput across languages.

**Data Query:**
```sql
SELECT model_id, language, AVG(throughput) AS avg_throughput
FROM benchmark_runs
WHERE device = 'cpu'
GROUP BY model_id, language
ORDER BY model_id, language;
```

**Plotly Configuration:**
```javascript
{
  type: 'bar',
  x: languages,  // ['ar', 'bg', 'ca', ...]
  y: throughputs,  // [12.5, 11.8, 13.2, ...]
  name: model_id,
  hovertemplate: '<b>%{x}</b><br>Throughput: %{y:.1f} seg/sec<extra></extra>'
}
```

### Chart 2: BLEU Score Heatmap

**Purpose:** Identify quality variations across languages and models.

**Data Query:**
```sql
SELECT model_id, language, bleu_score
FROM benchmark_runs
WHERE device = 'cuda' AND bleu_score IS NOT NULL
ORDER BY model_id, language;
```

**Plotly Configuration:**
```javascript
{
  type: 'heatmap',
  z: bleu_scores,  // 2D array [models x languages]
  x: languages,
  y: models,
  colorscale: [
    [0, 'rgb(255,0,0)'],      // Red for low scores
    [0.5, 'rgb(255,255,0)'],  // Yellow for medium
    [1, 'rgb(0,255,0)']       // Green for high scores
  ],
  hovertemplate: 'Model: %{y}<br>Language: %{x}<br>BLEU: %{z:.1f}<extra></extra>'
}
```

### Chart 3: Memory Scatter Plot

**Purpose:** Visualize RAM vs VRAM usage for GPU models.

**Data Query:**
```sql
SELECT model_id, peak_memory_mb, peak_vram_mb
FROM benchmark_runs
WHERE device = 'cuda' AND peak_vram_mb IS NOT NULL;
```

**Plotly Configuration:**
```javascript
{
  type: 'scatter',
  mode: 'markers',
  x: ram_usage,
  y: vram_usage,
  text: model_ids,
  marker: {
    size: 12,
    color: model_ids,  // Color by model
    colorscale: 'Viridis'
  },
  hovertemplate: '<b>%{text}</b><br>RAM: %{x} MB<br>VRAM: %{y} MB<extra></extra>'
}
```

### Chart 4: Latency Box Plot

**Purpose:** Show latency distribution and identify outliers.

**Data Query:**
```sql
SELECT model_id, latency_p50, latency_p95, latency_p99
FROM benchmark_runs
WHERE language = 'fr' AND device = 'cpu';
```

**Plotly Configuration:**
```javascript
{
  type: 'box',
  y: latencies,  // All latency samples
  x: model_ids,
  boxmean: 'sd',  // Show mean and standard deviation
  hovertemplate: 'P50: %{q1}<br>P95: %{q3}<br>Max: %{max}<extra></extra>'
}
```

---

## Quality Dimensions

### 1. Usability (5/5)
**Measurement:**
- [ ] Non-technical users can query benchmarks without SQL
- [ ] Charts load in <2 seconds
- [ ] Mobile-responsive design (tablet/phone)

**User Testing:**
- 5 users complete query task in <30 seconds (avg)
- Zero errors in export functionality
- Accessibility score (WCAG 2.1 AA)

### 2. Performance (4/5)
**Measurement:**
- [ ] Query results render in <500ms
- [ ] Chart generation in <2 seconds
- [ ] Export large datasets (1000+ rows) in <5 seconds

**Load Testing:**
- 10 concurrent users: No performance degradation
- Database with 10,000 runs: Queries remain <500ms

### 3. Correctness (5/5)
**Measurement:**
- [ ] Chart data matches database queries exactly
- [ ] Export files contain correct data (verified checksums)
- [ ] Calculations (speedup, averages) mathematically correct

**Validation:**
```python
def test_chart_data_accuracy():
    db_results = db.query("SELECT throughput FROM benchmark_runs WHERE model_id = 'm2m100_418m'")
    chart_data = dashboard.get_chart_data('throughput', model='m2m100_418m')
    assert db_results == chart_data
```

### 4. Maintainability (5/5)
**Measurement:**
- [ ] Add new chart in <100 lines of code
- [ ] New metrics require only database schema update
- [ ] Frontend/backend separation (REST API)

**Architecture:**
- Backend: Flask REST API (`/api/benchmarks`, `/api/charts`)
- Frontend: Vanilla JS + Plotly (no heavy frameworks)
- Database: SQLite (portable, zero-config)

### 5. Accessibility (4/5)
**Measurement:**
- [ ] Keyboard navigation supported
- [ ] Screen reader compatible (ARIA labels)
- [ ] High contrast mode available
- [ ] Color-blind friendly palettes

**Compliance:**
- WCAG 2.1 Level AA (minimum)
- Test with NVDA screen reader
- Color contrast ratio ≥4.5:1

---

## Acceptance Criteria

### Functional Acceptance

1. **Query Interface**
   - [ ] Users can filter by model, language, device, cache status
   - [ ] Results display in <500ms
   - [ ] Empty query shows all results (paginated)

2. **Comparison Views**
   - [ ] Model comparison table functional
   - [ ] Language coverage heatmap renders
   - [ ] CPU vs GPU speedup chart accurate

3. **Export**
   - [ ] CSV export contains correct columns
   - [ ] JSON export includes all metadata
   - [ ] PNG export creates valid image file

4. **Recommendation Engine**
   - [ ] Returns valid model based on constraints
   - [ ] Shows top 3 alternatives
   - [ ] Handles no-match scenario gracefully

### Non-Functional Acceptance

5. **Performance**
   - [ ] Dashboard loads in <3 seconds
   - [ ] Chart rendering in <2 seconds
   - [ ] Export 1000 rows in <5 seconds

6. **Usability**
   - [ ] User completes query task in <1 minute (first-time user)
   - [ ] Zero critical accessibility issues (WAVE scan)
   - [ ] Mobile-responsive (tested on iPhone, Android)

7. **Reliability**
   - [ ] Zero crashes in 100 query operations
   - [ ] Database errors display user-friendly messages
   - [ ] Graceful degradation if charts fail to render

---

## Implementation Guidance

### Backend API (Flask)

```python
# src/benchmarking/api.py

from flask import Flask, request, jsonify
from src.benchmarking.storage import BenchmarkDatabase

app = Flask(__name__)
db = BenchmarkDatabase("data/benchmarks/benchmarks.db")

@app.route('/api/benchmarks', methods=['GET'])
def get_benchmarks():
    """Query benchmark results."""
    model = request.args.get('model', 'all')
    language = request.args.get('language', 'all')
    device = request.args.get('device', 'all')

    results = db.query_benchmarks(
        model=None if model == 'all' else model,
        language=None if language == 'all' else language,
        device=None if device == 'all' else device
    )

    return jsonify({
        'total': len(results),
        'results': [r.to_dict() for r in results]
    })

@app.route('/api/charts/throughput', methods=['GET'])
def chart_throughput():
    """Get data for throughput chart."""
    language = request.args.get('language', 'fr')
    device = request.args.get('device', 'cpu')

    data = db.query("""
        SELECT model_id, AVG(throughput) AS avg_throughput
        FROM benchmark_runs
        WHERE language = ? AND device = ?
        GROUP BY model_id
    """, (language, device))

    return jsonify({
        'labels': [row['model_id'] for row in data],
        'values': [row['avg_throughput'] for row in data]
    })

@app.route('/api/export/csv', methods=['POST'])
def export_csv():
    """Export query results as CSV."""
    query_params = request.json
    results = db.query_benchmarks(**query_params)

    csv_data = "model_id,language,device,throughput,latency_p95,memory,bleu_score\n"
    for r in results:
        csv_data += f"{r.model_id},{r.language},{r.device},{r.throughput},{r.latency_p95},{r.memory},{r.bleu_score}\n"

    return csv_data, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=benchmark_export.csv'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
```

### Frontend (HTML + JavaScript)

```html
<!-- src/benchmarking/ui/index.html -->

<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hugo Translator Benchmarks</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
  <nav class="navbar">
    <h1>📊 Hugo Translator Benchmarks</h1>
  </nav>

  <div class="container">
    <div class="query-builder card">
      <h2>Query Builder</h2>
      <form id="query-form">
        <select id="model" name="model">
          <option value="all">All Models</option>
          <!-- Populated dynamically -->
        </select>
        <select id="language" name="language">
          <option value="all">All Languages</option>
          <!-- Populated dynamically -->
        </select>
        <button type="submit">Run Query</button>
      </form>
    </div>

    <div class="results card">
      <h2>Results</h2>
      <table id="results-table"></table>
    </div>

    <div class="chart-container card">
      <h2>Throughput Comparison</h2>
      <div id="chart-throughput"></div>
    </div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

```javascript
// src/benchmarking/ui/static/app.js

async function fetchBenchmarks(model = 'all', language = 'all') {
  const response = await fetch(`/api/benchmarks?model=${model}&language=${language}`);
  const data = await response.json();
  renderTable(data.results);
  renderChart(data.results);
}

function renderTable(results) {
  const table = document.getElementById('results-table');
  table.innerHTML = `
    <thead>
      <tr>
        <th>Model</th><th>Language</th><th>Device</th><th>Throughput</th>
      </tr>
    </thead>
    <tbody>
      ${results.map(r => `
        <tr>
          <td>${r.model_id}</td>
          <td>${r.language}</td>
          <td>${r.device}</td>
          <td>${r.throughput.toFixed(1)} seg/sec</td>
        </tr>
      `).join('')}
    </tbody>
  `;
}

function renderChart(results) {
  const data = [{
    x: results.map(r => r.model_id),
    y: results.map(r => r.throughput),
    type: 'bar'
  }];

  const layout = {
    title: 'Model Throughput Comparison',
    xaxis: { title: 'Model' },
    yaxis: { title: 'Throughput (seg/sec)' }
  };

  Plotly.newPlot('chart-throughput', data, layout);
}

// Initialize on page load
document.getElementById('query-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const model = document.getElementById('model').value;
  const language = document.getElementById('language').value;
  fetchBenchmarks(model, language);
});

fetchBenchmarks();  // Load default view
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-28 | System | Initial specification |

---

## Related Specifications

- [REQUIREMENTS.md](../REQUIREMENTS.md) - Parent requirements
- [COVERAGE_REQUIREMENTS.md](COVERAGE_REQUIREMENTS.md) - Benchmark execution
- [DATA_SOURCES.md](DATA_SOURCES.md) - Data sources and corpus
