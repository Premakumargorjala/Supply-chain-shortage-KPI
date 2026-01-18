# Supply Chain Shortage KPI Dashboard

A web-based dashboard application for monitoring and analyzing picking shortages in the Metrohm Spectro Fishbowl inventory system. This application provides real-time shortage KPIs, BOM comparison tools, and detailed inventory analysis.

## Features

### 📦 Shortage Dashboard
- **True Material Shortages**: Components requiring immediate procurement action
- **WIP Shortages**: Components waiting on manufacturing orders
- **Committed Elsewhere**: Stock allocated to other orders
- **Trend Analysis**: Weekly and monthly shortage trends
- **Aging Analysis**: Breakdown of shortages by age buckets

### 🔍 BOM Comparison Tool
- Compare Bill of Materials across multiple part numbers
- Find common and unique components between products
- View available inventory with location details
- Filter results by stock status, sub-assembly type, part number, and description
- Export comparison data to Excel (CSV format)

## Requirements

- Python 3.7+
- MySQL/MariaDB client libraries (for pymysql)
- Access to MetrohmSpectro Fishbowl database

## Installation

1. Clone this repository:
```bash
git clone https://github.com/Premakumargorjala/Supply-chain-shortage-KPI.git
cd Supply-chain-shortage-KPI
```

2. Install required Python packages:
```bash
pip install flask pymysql
```

3. Update database connection settings in `app.py` if needed:
```python
def get_connection():
    return pymysql.connect(
        host='451-srv-fbwl01',
        port=3306,
        user='ReadUser',
        password='Metrohm2026!',
        database='MetrohmSpectro'
    )
```

## Usage

### Start the Web Server

```bash
python app.py
```

The application will start on:
- **Local**: http://localhost:5555
- **Network**: http://<your-ip>:5555

### Access the Dashboard

1. **Shortage Dashboard**: Navigate to http://localhost:5555
   - View real-time shortage KPIs
   - Analyze shortage trends
   - Filter by shortage category

2. **BOM Comparison**: Navigate to http://localhost:5555/bom-compare
   - Enter multiple part numbers to compare
   - View common and unique components
   - Filter and export results

## Project Structure

```
Supply-chain-shortage-KPI/
├── app.py                                    # Main Flask application
├── shortage_kpi_dashboard.py                # Standalone dashboard script
├── shortage_kpi_queries.sql                 # SQL queries for analysis
├── check_part.py                            # Part lookup utility
├── common_subassemblies.py                  # BOM comparison utility
├── MetrohmSpectro_Database_Reference.md     # Database documentation
└── README.md                                 # This file
```

## API Endpoints

- `GET /` - Shortage Dashboard
- `GET /bom-compare` - BOM Comparison Tool
- `POST /api/bom-compare` - Compare BOMs (JSON)
- `POST /api/bom-export` - Export BOM comparison to CSV
- `GET /api/search-parts` - Search parts by number/description

## Database Schema

See `MetrohmSpectro_Database_Reference.md` for complete database documentation.

Key tables:
- `part` - Inventory parts
- `bom` / `bomitem` - Bill of Materials
- `pickitem` - Pick items (status 5 = Short)
- `tag` - Inventory locations and quantities
- `location` - Warehouse locations

## Features in Detail

### BOM Comparison
- Recursively explodes BOMs up to 5 levels deep
- Identifies common components shared across all compared parts
- Shows unique components for each part
- Displays inventory quantities with location breakdown
- Filters by stock status, sub-assembly type, part number, description
- Exports to Excel-compatible CSV format

### Shortage Categorization
- **TRUE Shortage**: No available inventory AND no WIP
- **WIP Shortage**: No available inventory BUT WIP exists
- **Committed Elsewhere**: Available inventory exists but allocated

## Configuration

### Port
Default port is 5555. To change it, edit `app.py`:
```python
app.run(host='0.0.0.0', port=5555, debug=False)
```

### Database
Update connection parameters in the `get_connection()` function.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is for internal use at Metrohm Spectro.

## Support

For issues or questions, please contact the development team.

## Changelog

### Version 1.0
- Initial release with Shortage Dashboard
- BOM Comparison Tool
- Filter and export functionality
- Real-time inventory analysis

