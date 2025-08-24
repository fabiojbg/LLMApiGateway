document.addEventListener('DOMContentLoaded', function () {
    const messageArea = document.getElementById('messageArea');
    const darkModeToggle = document.getElementById('darkModeToggle');
    const bodyElement = document.body;
    const themeSelector = document.getElementById('themeSelector');
    const saveButton = document.getElementById('saveButton');

    const tabRules = document.getElementById('tabRules');
    const tabProviders = document.getElementById('tabProviders');
    const editorContainerRules = document.getElementById('editor-container-rules');
    const editorContainerProviders = document.getElementById('editor-container-providers');
    const jsonEditorRulesTextArea = document.getElementById('jsonEditorRules');
    const jsonEditorProvidersTextArea = document.getElementById('jsonEditorProviders');

    let editorRules, editorProviders;
    let activeEditor = 'rules'; // 'rules' or 'providers'

    // --- Dark Mode Logic ---
    function setDarkMode(isDark) {
        bodyElement.classList.toggle('dark-mode', isDark);
        localStorage.setItem('darkMode', isDark ? 'enabled' : 'disabled');
        updateDarkModeIcon();
    }

    function updateDarkModeIcon() {
        if (bodyElement.classList.contains('dark-mode')) {
            //darkModeToggle.innerHTML = '<span class="icon-placeholder">☀️</span>'; // Sun icon for light mode
            darkModeToggle.setAttribute('aria-label', 'Switch to light mode');
        } else {
            //darkModeToggle.innerHTML = '<span class="icon-placeholder">🌙</span>'; // Moon icon for dark mode
            darkModeToggle.setAttribute('aria-label', 'Switch to dark mode');
        }
    }

    darkModeToggle.addEventListener('click', () => {
        setDarkMode(!bodyElement.classList.contains('dark-mode'));
    });

    // Apply saved dark mode preference on load
    const savedDarkMode = localStorage.getItem('darkMode');
    if (savedDarkMode === 'enabled') {
        setDarkMode(true);
    } else if (savedDarkMode === 'disabled') {
        setDarkMode(false);
    } else { // Not set, use prefers-color-scheme
        setDarkMode(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    }
    // Listen for system changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
        if (localStorage.getItem('darkMode') === null) { // Only if user hasn't set a preference
            setDarkMode(e.matches);
        }
    });


    // --- CodeMirror Initialization ---
    function initCodeMirror(textareaElement, theme) {
        return CodeMirror.fromTextArea(textareaElement, {
            lineNumbers: true,
            mode: { name: "javascript", json: true }, // Handles JSON with comments (JSONC-like)
            theme: theme,
            gutters: ["CodeMirror-lint-markers"],
            lint: true, // Use the standard JSON lint addon
            matchBrackets: true,
            autoCloseBrackets: true,
            lineWrapping: true,
        });
    }

    // --- Theme Selector Logic ---
    const themes = [
        { name: 'material-darker', displayName: 'Material Darker' },
        { name: 'dracula', displayName: 'Dracula' },
        { name: 'monokai', displayName: 'Monokai' },
        { name: 'nord', displayName: 'Nord' },
        { name: 'eclipse', displayName: 'Eclipse' }
    ];

    themes.forEach(theme => {
        const option = document.createElement('option');
        option.value = theme.name;
        option.textContent = theme.displayName;
        themeSelector.appendChild(option);
    });

    function applyThemeToEditor(editorInstance, themeName) {
        if (editorInstance) {
            editorInstance.setOption("theme", themeName);
        }
    }

    function applyThemeToAllEditors(themeName) {
        applyThemeToEditor(editorRules, themeName);
        applyThemeToEditor(editorProviders, themeName);
        localStorage.setItem('codeMirrorTheme', themeName);
    }

    const savedTheme = localStorage.getItem('codeMirrorTheme') || 'material-darker';
    applyThemeToAllEditors(savedTheme);
    themeSelector.value = savedTheme;

    themeSelector.addEventListener('change', function () {
        applyThemeToAllEditors(this.value);
    });

    // --- Tab Switching Logic ---
    function switchTab(tabName) {
        activeEditor = tabName;
        if (tabName === 'rules') {
            tabRules.classList.add('active');
            tabProviders.classList.remove('active');
            editorContainerRules.classList.add('active');
            editorContainerRules.style.display = 'block';
            editorContainerProviders.classList.remove('active');
            editorContainerProviders.style.display = 'none';
            if (!editorRules) {
                editorRules = initCodeMirror(jsonEditorRulesTextArea, themeSelector.value);
            }
            loadEditorData(editorRules, '/v1/config/models-rules', 'Fallback Rules');
            if (editorRules) editorRules.refresh();
        } else if (tabName === 'providers') {
            tabRules.classList.remove('active');
            tabProviders.classList.add('active');
            editorContainerRules.classList.remove('active');
            editorContainerRules.style.display = 'none';
            editorContainerProviders.classList.add('active');
            editorContainerProviders.style.display = 'block';
            if (!editorProviders) {
                editorProviders = initCodeMirror(jsonEditorProvidersTextArea, themeSelector.value);
            }
            loadEditorData(editorProviders, '/v1/config/providers', 'Providers'); // New endpoint
            if (editorProviders) editorProviders.refresh();
        }
    }

    tabRules.addEventListener('click', () => switchTab('rules'));
    tabProviders.addEventListener('click', () => switchTab('providers'));

    // --- Data Loading ---
    function loadEditorData(editorInstance, endpoint, configName) {
        if (!editorInstance) return;

        messageArea.textContent = `Loading ${configName}...`;
        messageArea.className = 'info';

        fetch(endpoint)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.text();
            })
            .then(textData => {
                editorInstance.setValue(textData);
                messageArea.textContent = `${configName} loaded successfully.`;
                messageArea.className = 'success';
            })
            .catch(error => {
                console.error(`Error fetching ${configName}:`, error);
                messageArea.textContent = `Error fetching ${configName}: ${error.message}`;
                messageArea.className = 'error';
                editorInstance.setValue(`// Error loading ${configName}.\n// ${error.message}`);
            });
    }

    // --- Save Configuration ---
    saveButton.addEventListener('click', function () {
        let currentEditorInstance;
        let endpoint;
        let configName;

        if (activeEditor === 'rules') {
            currentEditorInstance = editorRules;
            endpoint = '/v1/config/models-rules';
            configName = 'Fallback Rules';
        } else if (activeEditor === 'providers') {
            currentEditorInstance = editorProviders;
            endpoint = '/v1/config/providers'; // New endpoint
            configName = 'Providers';
        } else {
            messageArea.textContent = 'No active editor selected.';
            messageArea.className = 'error';
            return;
        }

        if (!currentEditorInstance) {
            messageArea.textContent = `Editor for ${configName} is not initialized.`;
            messageArea.className = 'error';
            return;
        }

        const rawEditorContent = currentEditorInstance.getValue();

        saveButton.disabled = true;
        saveButton.textContent = 'Saving...';
        messageArea.textContent = `Saving ${configName}...`;
        messageArea.className = 'info';

        fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'text/plain', // Send as raw text
            },
            body: rawEditorContent
        })
        .then(response => {
            saveButton.disabled = false;
            saveButton.textContent = 'Save Configuration';
            // Try to parse JSON, but handle cases where it might not be JSON (e.g., network error page)
            return response.text().then(text => {
                try {
                    return { status: response.status, body: JSON.parse(text) };
                } catch (e) {
                    // If JSON parsing fails, the body might be plain text (e.g. HTML error page)
                    return { status: response.status, body: { detail: text }, isRawTextError: true };
                }
            });
        })
        .then(({ status, body, isRawTextError }) => {
            if (status === 200 && body.message) {
                messageArea.textContent = `${configName} ${body.message.toLowerCase()}`;
                messageArea.className = 'success';
            } else {
                messageArea.className = 'error';
                let errorMessage = `Error saving ${configName} (HTTP ${status}): `;
                if (isRawTextError) {
                    errorMessage += body.detail; // Show the raw text error
                } else if (body.detail && Array.isArray(body.errors)) { // Pydantic validation errors
                    errorMessage += `${body.detail}. Issues:\n`;
                    const errorDetails = body.errors.map(err => {
                        const loc = err.loc ? err.loc.join(' -> ') : 'N/A';
                        return `- Location: ${loc}, Message: ${err.msg}, Type: ${err.type}`;
                    }).join('\n');
                    messageArea.innerHTML = `<strong>Validation Error for ${configName} (HTTP ${status}):</strong><pre>${body.detail}\n${errorDetails}</pre>`;
                } else if (body.detail) {
                     messageArea.innerHTML = `<strong>Error saving ${configName} (HTTP ${status}):</strong><pre>${body.detail}</pre>`;
                } else {
                     messageArea.textContent = errorMessage + (JSON.stringify(body) || "Unknown error");
                }
                if (!messageArea.innerHTML) { // if innerHTML wasn't set by specific error formatting
                    messageArea.className = 'error';
                }
            }
        })
        .catch(error => {
            console.error(`Error saving ${configName}:`, error);
            messageArea.textContent = `Error saving ${configName}: ${error.message}`;
            messageArea.className = 'error';
            saveButton.disabled = false;
            saveButton.textContent = 'Save Configuration';
        });
    });

    // --- Initialize ---
    // Load default tab (rules)
    switchTab('rules');
});
