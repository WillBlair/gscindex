# Global Supply Chain Index

A real-time dashboard that aggregates and visualizes global supply chain health metrics. This tool calculates a composite "Supply Chain Health Index" (0–100) based on data from multiple sectors including shipping, energy, demand, geopolitics, and weather.

## Features

- **Composite Health Score**: A single weighted index (0-100) representing overall supply chain stability.
- **Multi-Category Analysis**:
  - **Shipping**: Port congestion, freight rates, and transit times.
  - **Energy**: Oil prices and energy availability.
  - **Demand**: Consumer sentiment and manufacturing orders.
  - **Geopolitics**: Political stability and trade risk.
  - **Weather**: Severe weather events impacting logistics.
- **Real-time Visualization**: Interactive charts and gauges using Plotly and Dash.
- **Modular Architecture**: Pluggable data providers and a flexible scoring engine.

## Tech Stack

- **Frontend/Backend**: [Dash](https://dash.plotly.com/) (Python)
- **UI Components**: [Dash Bootstrap Components](https://dash-bootstrap-components.opensource.faculty.ai/)
- **Data Processing**: Pandas, NumPy
- **Visualization**: Plotly

## Setup & Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/WillBlair/gscindex.git
    cd gscindex
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    Copy `.env.example` to `.env` and add your API keys.
    ```bash
    cp .env.example .env
    ```
    *Note: You will need valid API keys for the configured data providers (e.g., FRED, OpenWeather, etc.) to fetch real-time data.*

5.  **Run the application:**
    ```bash
    python app.py
    ```

6.  **Access the dashboard:**
    Open your browser and navigate to `http://127.0.0.1:8050`.

## Project Structure

```
gscindex/
├── app.py                 # Application entry point
├── config.py              # Configuration (weights, API keys, constants)
├── components/            # Dash UI components (charts, cards, layout)
├── data/                  # Data fetching and aggregation logic
│   ├── aggregator.py      # Combines data from all providers
│   └── providers/         # Individual data provider modules
├── scoring/               # Scoring engine logic
│   └── engine.py          # Calculates the composite index
├── assets/                # Static assets (CSS, images)
└── requirements.txt       # Python dependencies
```

## Customization

- **Adjusting Weights**: You can modify the importance of each category in `config.py` by changing the `CATEGORY_WEIGHTS` dictionary.
- **Adding Providers**: Create a new module in `data/providers/` inheriting from the base provider class and register it in `data/aggregator.py`.

## License

[MIT License](LICENSE)
