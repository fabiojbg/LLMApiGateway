document.addEventListener('DOMContentLoaded', () => {
    const periodSelector = document.getElementById('periodSelector');
    const refreshButton = document.getElementById('refreshButton');
    const statsArea = document.getElementById('statsArea');
    const messageArea = document.getElementById('messageArea');
    const darkModeToggle = document.getElementById('darkModeToggle');

    // --- Dark Mode Logic ---
    const applyTheme = (theme) => {
        if (theme === 'dark') {
            document.body.classList.add('dark-mode');
        } else {
            document.body.classList.remove('dark-mode');
        }
        localStorage.setItem('theme', theme);
    };

    const toggleDarkMode = () => {
        const currentTheme = localStorage.getItem('theme') || 'light';
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        applyTheme(newTheme);
    };

    // Initialize theme on load
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);

    darkModeToggle.addEventListener('click', toggleDarkMode);

    // --- Fetch and Render Statistics Logic ---
    const showMessage = (message, isError = false) => {
        messageArea.textContent = message;
        messageArea.className = isError ? 'error' : '';
    };

    const createStatsTable = (data) => {
        if (!data || data.length === 0) {
            return '<p>No data available for the selected period.</p>';
        }

        const metrics = [
            'prompt_tokens', 'completion_tokens', 'total_tokens',
            'reasoning_tokens', 'cached_tokens', 'count', 'cost'
        ];

        let html = '';
        const groupedByPeriod = data.reduce((acc, current) => {
            const periodKey = current.time_period;
            if (!acc[periodKey]) {
                acc[periodKey] = [];
            }
            acc[periodKey].push(current);
            return acc;
        }, {});

        for (const periodKey in groupedByPeriod) {
            html += `<h2>Period: ${periodKey}</h2>`;
            html += `<table>`;
            html += `<thead><tr><th>Model</th>`;
            metrics.forEach(metric => {
                html += `<th>${metric.replace('_', ' ').split(' ') 
                          .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                          .join(' ')
                          .replace(' ', '<br>')}</th>`;
            });
            html += `</tr></thead>`;
            html += `<tbody>`;

            groupedByPeriod[periodKey].forEach(row => {
                html += `<tr>`;
                html += `<td>${row.model || 'N/A'}</td>`;
                metrics.forEach(metric => {
                    let value = row[metric];
                    if (metric === 'cost' && typeof value === 'number') {
                        value = value.toFixed(4); // Format cost to 4 decimal places
                    }
                    html += `<td>${typeof value === 'number' ? value.toLocaleString() : value}</td>`;
                });
                html += `</tr>`;
            });
            html += `</tbody></table>`;
        }
        return html;
    };

    const fetchAndRenderStats = async () => {
        const selectedPeriod = periodSelector.value;
        statsArea.innerHTML = '<p>Loading statistics...</p>';
        showMessage('');

        try {
            const response = await fetch(`/v1/api/usage-stats/${selectedPeriod}`);
            const data = await response.json();

            if (!response.ok) {
                const errorMessage = data.detail ? data.detail : `Error: ${response.status} ${response.statusText}`;
                showMessage(errorMessage, true);
                statsArea.innerHTML = '';
                return;
            }
            
            statsArea.innerHTML = createStatsTable(data);
            if (data.length === 0) {
                 showMessage('No data available for the selected period.', false);
            } else {
                showMessage('Statistics loaded successfully.');
            }

        } catch (error) {
            console.error('Failed to fetch usage statistics:', error);
            showMessage(`Failed to load statistics: ${error.message}`, true);
            statsArea.innerHTML = '';
        }
    };

    // Event Listeners
    refreshButton.addEventListener('click', fetchAndRenderStats);
    periodSelector.addEventListener('change', fetchAndRenderStats);

    // Initial load of statistics
    fetchAndRenderStats();

    // --- Tab Switching Logic ---
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tab = button.dataset.tab;

            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            button.classList.add('active');
            document.getElementById(`${tab}TabContent`).classList.add('active');

            // Load data for the active tab (if it's records)
            if (tab === 'records') {
                currentPage = 1; // Reset to first page when switching to records tab
                fetchAndRenderRecords();
            } else {
                fetchAndRenderStats();
            }
        });
    });

    // --- Usage Records Logic (New) ---
    const recordsArea = document.getElementById('recordsArea');
    const prevPageButton = document.getElementById('prevPage');
    const nextPageButton = document.getElementById('nextPage');
    const recordRefreshButton = document.getElementById('recordRefreshButton');
    const pageInfoSpan = document.getElementById('pageInfo');
    const recordsPerPage = 25; // As per the task description
    let currentPage = 1;

    const createRecordsTable = (data) => {
        if (!data || data.length === 0) {
            return '<p>No usage records available.</p>';
        }

        const headers = Object.keys(data[0]);
        let html = '<table><thead><tr>';
        headers.forEach(header => {
            html += `<th>${header.replace('_', ' ').split(' ')
                                 .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                                 .join(' ')
                                 .replace(' ', '<br>')}</th>`;
        });
        html += '</tr></thead><tbody>';

        data.forEach(row => {
            html += '<tr>';
            headers.forEach(header => {
                let formattedValue = row[header];
                if (header === 'timestamp') {
                    // Example: '2025-08-23T20:54:25.987549' -> '2025-08-23T20:54:25.99'
                    if (typeof formattedValue === 'string' && formattedValue.includes('T') && formattedValue.includes('.')) {
                        const parts = formattedValue.split('.');
                        if (parts.length > 1) {
                            const milliseconds = parts[1].substring(0, 2);
                            formattedValue = `${parts[0]}.${milliseconds}`;
                        }
                    }
                } else if (header === 'cost') {
                    // Example: '0.01' -> '0.0100'
                    if (typeof formattedValue === 'number') {
                        formattedValue = formattedValue.toFixed(4);
                    }
                }
                html += `<td>${typeof formattedValue === 'number' ? formattedValue.toLocaleString() : formattedValue}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        return html;
    };

    const updatePaginationControls = (totalRecords) => {
        const totalPages = Math.ceil(totalRecords / recordsPerPage);
        pageInfoSpan.textContent = `Page ${currentPage} of ${totalPages || 1}`;
        prevPageButton.disabled = currentPage === 1;
        nextPageButton.disabled = currentPage === totalPages || totalRecords === 0;
    };

    const fetchAndRenderRecords = async () => {
        recordsArea.innerHTML = '<p>Loading usage records...</p>';
        showMessage('');

        const offset = (currentPage - 1) * recordsPerPage;

        try {
            const response = await fetch(`/v1/api/usage-records?limit=${recordsPerPage}&offset=${offset}`);
            const responseData = await response.json(); // Renamed to avoid confusion with internal 'data'

            if (!response.ok) {
                const errorMessage = responseData.detail ? responseData.detail : `Error: ${response.status} ${response.statusText}`;
                showMessage(errorMessage, true);
                recordsArea.innerHTML = '';
                updatePaginationControls(0);
                return;
            }

            const records = responseData.records;
            const totalRecords = responseData.total_records;

            recordsArea.innerHTML = createRecordsTable(records);
            updatePaginationControls(totalRecords);

            if (records.length === 0 && currentPage === 1) {
                showMessage('No usage records found.', false);
            } else {
                showMessage('Usage records loaded successfully.');
            }

        } catch (error) {
            console.error('Failed to fetch usage records:', error);
            showMessage(`Failed to load usage records: ${error.message}`, true);
            recordsArea.innerHTML = '';
            updatePaginationControls(0);
        }
    };

    prevPageButton.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            fetchAndRenderRecords();
        }
    });

    nextPageButton.addEventListener('click', () => {
        currentPage++; // We will check bounds in updatePaginationControls or based on API response
        fetchAndRenderRecords();
    });

    recordRefreshButton.addEventListener('click', () => {
        currentPage = 1; // Reset to the first page on refresh
        fetchAndRenderRecords();
    });

    // Ensure initial load respects the default tab
    const activeTab = document.querySelector('.tab-button.active');
    if (activeTab && activeTab.dataset.tab === 'records') {
        fetchAndRenderRecords();
    } else {
        fetchAndRenderStats(); // Default to stats if no active tab or if stats is active
    }

});
