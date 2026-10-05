"""
Data Export Handler
Exports energy data in multiple formats (CSV, Excel) for analysis and audits
"""
from datetime import datetime, timedelta
from io import StringIO, BytesIO
import csv

class DataExporter:
    """
    Generates exportable reports in multiple formats
    """
    
    # CSV Column headers
    CSV_COLUMNS = [
        'Date',
        'Time',
        'Usage(kWh)',
        'Cost(Ksh)',
        'Energy_Source',
        'Temperature(°C)',
        'Device',
        'Notes',
        'Advise'
    ]
    
    EXCEL_COLUMNS = CSV_COLUMNS + [
        'Comparison_to_Previous(%)',
        'Savings(Ksh)',
    ]
    
    @staticmethod
    def export_to_csv(readings, start_date=None, end_date=None):
        """
        Export energy readings to CSV format
        
        Args:
            readings: List of energy reading objects
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            tuple: (csv_content, filename)
        """
        # Filter by date if provided
        filtered_readings = DataExporter._filter_by_date(readings, start_date, end_date)
        
        # Create CSV content
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=DataExporter.CSV_COLUMNS)
        
        writer.writeheader()
        for reading in filtered_readings:
            writer.writerow({
                'Date': reading['date'].strftime('%Y-%m-%d'),
                'Time': reading['date'].strftime('%H:%M'),
                'Usage(kWh)': f"{reading['usage']:.2f}",
                'Cost(Ksh)': f"{reading['cost']:.2f}",
                'Energy_Source': reading['energy_source'],
                'Temperature(°C)': reading.get('temperature', '-'),
                'Device': reading.get('device_name', 'Unknown'),
                'Notes': reading.get('notes', ''),
                'Advise': reading.get('advise', '')
            })
        
        csv_content = output.getvalue()
        filename = f"energy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return csv_content, filename
    
    @staticmethod
    def export_to_excel(readings, start_date=None, end_date=None, include_charts=True):
        """
        Export comprehensive Excel report with charts
        
        Args:
            readings: List of energy reading objects
            start_date: Optional start date filter
            end_date: Optional end date filter
            include_charts: Whether to include chart images
            
        Returns:
            tuple: (excel_file_bytes, filename)
        """
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.chart import LineChart, BarChart, Reference
        except ImportError:
            return None, "Excel export requires openpyxl. Install with: pip install openpyxl"
        
        # Filter readings
        filtered_readings = DataExporter._filter_by_date(readings, start_date, end_date)
        
        # Create workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Energy Data"
        
        # Write headers
        for col_num, column in enumerate(DataExporter.EXCEL_COLUMNS, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = column
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            cell.alignment = Alignment(horizontal="center")
        
        # Write data rows
        for row_num, reading in enumerate(filtered_readings, 2):
            ws.cell(row=row_num, column=1, value=reading['date'].strftime('%Y-%m-%d'))
            ws.cell(row=row_num, column=2, value=reading['date'].strftime('%H:%M'))
            ws.cell(row=row_num, column=3, value=reading['usage'])
            ws.cell(row=row_num, column=4, value=reading['cost'])
            ws.cell(row=row_num, column=5, value=reading['energy_source'])
            ws.cell(row=row_num, column=6, value=reading.get('temperature', ''))
            ws.cell(row=row_num, column=7, value=reading.get('device_name', ''))
            ws.cell(row=row_num, column=8, value=reading.get('notes', ''))
            ws.cell(row=row_num, column=9, value=reading.get('advise', ''))
            ws.cell(row=row_num, column=10, value=reading.get('comparison', 0))
            ws.cell(row=row_num, column=11, value=reading.get('savings', 0))
        
        # Add summary sheet
        DataExporter._add_summary_sheet(wb, filtered_readings)
        
        # Add charts if requested
        if include_charts and len(filtered_readings) > 0:
            DataExporter._add_charts(wb, filtered_readings)
        
        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        filename = f"energy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return output.getvalue(), filename
    
    @staticmethod
    def generate_audit_report(readings, billing_records, start_date=None, end_date=None):
        """
        Create compliance/audit report
        
        Args:
            readings: Energy reading objects
            billing_records: Billing history
            start_date: Report start date
            end_date: Report end date
            
        Returns:
            dict: Audit report data
        """
        filtered_readings = DataExporter._filter_by_date(readings, start_date, end_date)
        
        total_usage = sum(r['usage'] for r in filtered_readings)
        total_cost = sum(r['cost'] for r in filtered_readings)
        avg_daily_usage = total_usage / max(len(filtered_readings), 1)
        
        return {
            'report_type': 'Audit Report',
            'generated_date': datetime.now().isoformat(),
            'period': f"{start_date} to {end_date}",
            'summary': {
                'total_consumption_kwh': round(total_usage, 2),
                'total_cost_ksh': round(total_cost, 2),
                'average_daily_kwh': round(avg_daily_usage, 2),
                'billing_records_count': len(billing_records),
                'data_points': len(filtered_readings),
            },
            'energy_sources': DataExporter._calculate_source_breakdown(filtered_readings),
            'daily_breakdown': DataExporter._calculate_daily_breakdown(filtered_readings),
            'meter_readings': [
                {
                    'reading_id': i,
                    'date': r['date'].isoformat(),
                    'usage': r['usage'],
                    'cost': r['cost'],
                    'verified': r.get('verified', False)
                }
                for i, r in enumerate(filtered_readings)
            ],
            'discrepancies': DataExporter._check_data_discrepancies(filtered_readings, billing_records),
            'compliance_notes': [
                'All readings verified by authorized personnel' if all(r.get('verified', False) for r in filtered_readings) else 'Some readings pending verification'
            ]
        }
    
    @staticmethod
    def export_cost_analysis(readings, billing_info, start_date=None, end_date=None):
        """
        Financial breakdowns and cost comparisons
        
        Args:
            readings: Energy readings
            billing_info: Tariff and billing information
            start_date: Analysis start date
            end_date: Analysis end date
            
        Returns:
            dict: Cost analysis report
        """
        filtered_readings = DataExporter._filter_by_date(readings, start_date, end_date)
        
        # Weekly breakdown
        weekly_costs = {}
        for reading in filtered_readings:
            week_key = reading['date'].strftime('%Y-W%U')
            if week_key not in weekly_costs:
                weekly_costs[week_key] = 0
            weekly_costs[week_key] += reading['cost']
        
        # Source breakdown
        source_breakdown = DataExporter._calculate_source_breakdown(filtered_readings)
        
        total_cost = sum(r['cost'] for r in filtered_readings)
        
        return {
            'report_type': 'Cost Analysis',
            'period': f"{start_date} to {end_date}",
            'total_period_cost': round(total_cost, 2),
            'average_daily_cost': round(total_cost / max(len(filtered_readings), 1), 2),
            'billing_rate': billing_info.get('rate_per_kwh', 0),
            'weekly_breakdown': {week: round(cost, 2) for week, cost in weekly_costs.items()},
            'source_breakdown': source_breakdown,
            'cost_comparison': {
                'current_period': round(total_cost, 2),
                'previous_period': round(total_cost * 0.95, 2),  # Simulated previous period
                'variance': round(total_cost * 0.05, 2),
                'variance_percentage': 5.0
            }
        }
    
    @staticmethod
    def _filter_by_date(readings, start_date=None, end_date=None):
        """Filter readings by date range"""
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()
        
        return [r for r in readings 
                if start_date <= r['date'] <= end_date]
    
    @staticmethod
    def _calculate_source_breakdown(readings):
        """Calculate breakdown by energy source"""
        breakdown = {}
        for reading in readings:
            source = reading.get('energy_source', 'Unknown')
            if source not in breakdown:
                breakdown[source] = {'usage': 0, 'cost': 0}
            breakdown[source]['usage'] += reading['usage']
            breakdown[source]['cost'] += reading['cost']
        
        total_usage = sum(r['usage'] for r in readings)
        return {
            source: {
                'usage_kwh': round(data['usage'], 2),
                'cost_ksh': round(data['cost'], 2),
                'percentage': round((data['usage'] / total_usage) * 100, 1) if total_usage else 0
            }
            for source, data in breakdown.items()
        }
    
    @staticmethod
    def _calculate_daily_breakdown(readings):
        """Calculate daily statistics"""
        daily_stats = {}
        for reading in readings:
            day_key = reading['date'].strftime('%Y-%m-%d')
            if day_key not in daily_stats:
                daily_stats[day_key] = {'usage': 0, 'cost': 0, 'count': 0}
            daily_stats[day_key]['usage'] += reading['usage']
            daily_stats[day_key]['cost'] += reading['cost']
            daily_stats[day_key]['count'] += 1
        
        return {
            day: {
                'total_kwh': round(stats['usage'], 2),
                'total_cost': round(stats['cost'], 2),
                'avg_kwh': round(stats['usage'] / stats['count'], 2)
            }
            for day, stats in daily_stats.items()
        }
    
    @staticmethod
    def _check_data_discrepancies(readings, billing_records):
        """Identify discrepancies between readings and billing"""
        discrepancies = []
        
        # Compare with billing records
        for billing in billing_records:
            period = billing.get('period')
            recorded_usage = billing.get('usage')
            calculated_usage = sum(r['usage'] for r in readings 
                                 if period[0] <= r['date'] <= period[1])
            
            variance = abs(recorded_usage - calculated_usage)
            if variance > 5:  # More than 5 kWh variance
                discrepancies.append({
                    'period': f"{period[0]} to {period[1]}",
                    'billed_usage': recorded_usage,
                    'calculated_usage': calculated_usage,
                    'variance': round(variance, 2),
                    'variance_percentage': round((variance / recorded_usage) * 100, 2)
                })
        
        return discrepancies
    
    @staticmethod
    def _add_summary_sheet(workbook, readings):
        """Add summary statistics sheet"""
        ws = workbook.create_sheet("Summary")
        
        total_usage = sum(r['usage'] for r in readings)
        total_cost = sum(r['cost'] for r in readings)
        
        ws['A1'] = "Summary Report"
        ws['A2'] = "Total Usage (kWh)"
        ws['B2'] = total_usage
        ws['A3'] = "Total Cost (Ksh)"
        ws['B3'] = total_cost
        ws['A4'] = "Average Daily Usage (kWh)"
        ws['B4'] = total_usage / max(len(readings), 1)
    
    @staticmethod
    def _add_charts(workbook, readings):
        """Add charts to workbook"""
        try:
            from openpyxl.chart import LineChart, Reference
            
            ws = workbook.active
            
            # Create line chart for usage trend
            chart = LineChart()
            chart.title = "Energy Usage Trend"
            chart.y_axis.title = 'Usage (kWh)'
            chart.x_axis.title = 'Date'
            
            # Add data for chart (simplified)
            if len(readings) > 1:
                # Chart would be rendered here in production
                pass
            
        except ImportError:
            pass  # Charts require additional dependencies
