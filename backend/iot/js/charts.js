/**
 * charts.js — Chart.js Integration
 * TOYAMAS IoT Dashboard
 */

const Charts = (() => {

    let _salesChartInstance = null;
    let _reportChartInstance = null;
    let _currentChartType = 'hourly';

    // ──────────────────────────────────────
    // Color Palette
    // ──────────────────────────────────────

    const COLORS = {
        blue: '#2A91D8',
        blueLight: 'rgba(42,145,216,0.2)',
        green: '#34C38F',
        greenLight: 'rgba(52,195,143,0.2)',
        purple: '#7C5CE7',
        purpleLight: 'rgba(124,92,231,0.2)',
        orange: '#F0A940',
        orangeLight: 'rgba(240,169,64,0.2)',
        red: '#E85D5D',
        redLight: 'rgba(232,93,93,0.2)',
    };

    // ──────────────────────────────────────
    // Sales Chart (Overview)
    // ──────────────────────────────────────

    function renderSalesChart(data, chartType = 'hourly') {
        const ctx = document.getElementById('salesChart');
        if (!ctx) return;

        _currentChartType = chartType;

        // Destroy existing chart
        if (_salesChartInstance) {
            _salesChartInstance.destroy();
        }

        const labels = data.labels || [];
        const volumes = data.datasets?.volume || [];
        const transactions = data.datasets?.transactions || [];

        const isHourly = chartType === 'hourly';

        _salesChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Volume (Liter)',
                        data: volumes,
                        backgroundColor: COLORS.blueLight,
                        borderColor: COLORS.blue,
                        borderWidth: 2,
                        borderRadius: 4,
                        order: 1,
                    },
                    {
                        label: 'Transaksi',
                        data: transactions,
                        type: 'line',
                        borderColor: COLORS.green,
                        backgroundColor: 'transparent',
                        pointBackgroundColor: COLORS.green,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        pointRadius: 4,
                        tension: 0.3,
                        order: 0,
                        yAxisID: 'y1',
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            padding: 16,
                            font: {
                                size: 11,
                                weight: '600',
                                family: "'Plus Jakarta Sans', sans-serif",
                            },
                            color: '#7AAEC8',
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(255,255,255,0.95)',
                        titleColor: '#1A3A52',
                        bodyColor: '#1A3A52',
                        borderColor: '#e8f0f8',
                        borderWidth: 1,
                        cornerRadius: 8,
                        padding: 12,
                        boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                let value = context.raw || 0;
                                if (context.dataset.label === 'Volume (Liter)') {
                                    return label + ': ' + value.toFixed(1) + ' L';
                                }
                                if (context.dataset.label === 'Transaksi') {
                                    return label + ': ' + Math.round(value);
                                }
                                return label + ': ' + value;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            font: { size: 9, family: "'Plus Jakarta Sans', sans-serif" },
                            color: '#7AAEC8',
                            maxTicksLimit: isHourly ? 24 : 30,
                            callback: function(value, index, ticks) {
                                const label = this.getLabelForValue(value);
                                if (isHourly) {
                                    return label.replace(':00', '');
                                }
                                return label;
                            }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0,0,0,0.04)' },
                        ticks: {
                            font: { size: 9, family: "'Plus Jakarta Sans', sans-serif" },
                            color: '#7AAEC8',
                        },
                        title: {
                            display: true,
                            text: 'Liter',
                            color: '#7AAEC8',
                            font: { size: 9, weight: '600' },
                        }
                    },
                    y1: {
                        position: 'right',
                        beginAtZero: true,
                        grid: { display: false },
                        ticks: {
                            font: { size: 9, family: "'Plus Jakarta Sans', sans-serif" },
                            color: '#7AAEC8',
                            stepSize: 1,
                        },
                        title: {
                            display: true,
                            text: 'Transaksi',
                            color: '#7AAEC8',
                            font: { size: 9, weight: '600' },
                        }
                    }
                }
            }
        });
    }

    // ──────────────────────────────────────
    // Report Chart (Laporan)
    // ──────────────────────────────────────

    function renderReportChart(data, period = 'today') {
        const ctx = document.getElementById('reportChart');
        if (!ctx) return;

        if (_reportChartInstance) {
            _reportChartInstance.destroy();
        }

        const labels = data.labels || [];
        const volumes = data.datasets?.volume || [];
        const revenue = data.datasets?.revenue || [];

        // Hitung rata-rata
        const avg = volumes.length > 0 
            ? volumes.reduce((a, b) => a + b, 0) / volumes.length 
            : 0;

        _reportChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Volume (Liter)',
                        data: volumes,
                        backgroundColor: COLORS.blueLight,
                        borderColor: COLORS.blue,
                        borderWidth: 2,
                        borderRadius: 4,
                        order: 1,
                    },
                    {
                        label: 'Rata-rata',
                        data: Array(labels.length).fill(avg),
                        type: 'line',
                        borderColor: COLORS.orange,
                        backgroundColor: 'transparent',
                        borderDash: [6, 4],
                        pointRadius: 0,
                        order: 0,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            padding: 16,
                            font: {
                                size: 11,
                                weight: '600',
                                family: "'Plus Jakarta Sans', sans-serif",
                            },
                            color: '#7AAEC8',
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(255,255,255,0.95)',
                        titleColor: '#1A3A52',
                        bodyColor: '#1A3A52',
                        borderColor: '#e8f0f8',
                        borderWidth: 1,
                        cornerRadius: 8,
                        padding: 12,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                let value = context.raw || 0;
                                if (context.dataset.label === 'Volume (Liter)') {
                                    return label + ': ' + value.toFixed(1) + ' L';
                                }
                                if (context.dataset.label === 'Rata-rata') {
                                    return label + ': ' + value.toFixed(1) + ' L';
                                }
                                return label + ': ' + value;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            font: { size: 9, family: "'Plus Jakarta Sans', sans-serif" },
                            color: '#7AAEC8',
                            maxTicksLimit: 15,
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0,0,0,0.04)' },
                        ticks: {
                            font: { size: 9, family: "'Plus Jakarta Sans', sans-serif" },
                            color: '#7AAEC8',
                        },
                        title: {
                            display: true,
                            text: 'Liter',
                            color: '#7AAEC8',
                            font: { size: 9, weight: '600' },
                        }
                    }
                }
            }
        });
    }

    // ──────────────────────────────────────
    // Update Functions
    // ──────────────────────────────────────

    function updateSalesChart(data, chartType) {
        renderSalesChart(data, chartType);
    }

    function updateReportChart(data, period) {
        renderReportChart(data, period);
    }

    function getCurrentChartType() {
        return _currentChartType;
    }

    // ──────────────────────────────────────
    // Public API
    // ──────────────────────────────────────

    return {
        renderSalesChart,
        renderReportChart,
        updateSalesChart,
        updateReportChart,
        getCurrentChartType,
    };

})();

window.Charts = Charts;