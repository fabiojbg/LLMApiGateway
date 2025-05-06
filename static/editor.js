document.addEventListener('DOMContentLoaded', function () {
    const messageArea = document.getElementById('messageArea');
    const darkModeToggle = document.getElementById('darkModeToggle');
    const bodyElement = document.body;
    let editor;

    // Dark Mode Logic
    function setDarkMode(isDark) {
        if (isDark) {
            bodyElement.classList.add('dark-mode');
            localStorage.setItem('darkMode', 'enabled');
        } else {
            bodyElement.classList.remove('dark-mode');
            localStorage.setItem('darkMode', 'disabled');
        }
        // The button icon is handled by CSS based on the body class
    }

    // Event listener for dark mode toggle
    darkModeToggle.addEventListener('click', () => {
        setDarkMode(!bodyElement.classList.contains('dark-mode'));
    });

    // Apply saved dark mode preference on load
    if (localStorage.getItem('darkMode') === 'enabled') {
        setDarkMode(true);
    } else {
        setDarkMode(false); // Default to light mode if not set or disabled
    }


    try {
        editor = CodeMirror.fromTextArea(document.getElementById('jsonEditor'), {
            lineNumbers: true,
            mode: { name: "javascript", json: true },
            theme: "material-darker",
            gutters: ["CodeMirror-lint-markers"],
            lint: true,
            matchBrackets: true,
            autoCloseBrackets: true,
            lineWrapping: true,
        });

        // Theme Selector Logic
        const themeSelector = document.getElementById('themeSelector');
        const themes = [
            { name: 'material-darker', displayName: 'Material Darker' },
            { name: 'dracula', displayName: 'Dracula' },
            { name: 'monokai', displayName: 'Monokai' },
            { name: 'nord', displayName: 'Nord' },
            { name: 'eclipse', displayName: 'Eclipse' }
            // Add more themes here if their CSS is included in editor.html
        ];

        // Populate theme selector
        themes.forEach(theme => {
            const option = document.createElement('option');
            option.value = theme.name;
            option.textContent = theme.displayName;
            themeSelector.appendChild(option);
        });

        // Function to apply theme
        function applyTheme(themeName) {
            if (editor) {
                editor.setOption("theme", themeName);
            }
        }

        // Load saved theme from localStorage or default to material-darker
        const savedTheme = localStorage.getItem('codeMirrorTheme') || 'material-darker';
        applyTheme(savedTheme);
        themeSelector.value = savedTheme;

        // Event listener for theme change
        themeSelector.addEventListener('change', function () {
            const selectedTheme = this.value;
            applyTheme(selectedTheme);
            localStorage.setItem('codeMirrorTheme', selectedTheme);
        });

    } catch (e) {
        console.error("Failed to initialize CodeMirror:", e);
        messageArea.textContent = 'Error: Could not initialize code editor. Make sure you are online to load CodeMirror resources.';
        messageArea.className = 'error';
        // Fallback to a simple textarea if CodeMirror fails
        document.getElementById('jsonEditor').style.display = 'block'; 
        return; // Stop further execution if editor fails
    }


    // Fetch initial configuration
    fetch('/v1/config/models-rules') // This endpoint now returns raw text
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.text(); // Expect raw text
        })
        .then(textData => {
            if (editor) {
                editor.setValue(textData); // Set raw text in CodeMirror
            } else {
                 // Fallback if editor is not initialized
                document.getElementById('jsonEditor').value = textData;
            }
        })
        .catch(error => {
            console.error('Error fetching configuration:', error);
            messageArea.textContent = 'Error fetching configuration: ' + error.message;
            messageArea.className = 'error';
        });

    // Save button event listener
    document.getElementById('saveButton').addEventListener('click', function () {
        let rawEditorContent;
        if (editor) {
            rawEditorContent = editor.getValue(); // Get raw text from CodeMirror
        } else {
            // Fallback if editor is not initialized
            rawEditorContent = document.getElementById('jsonEditor').value;
        }
        
        // Client-side validation is removed here as the backend will handle
        // validation of the JSONC structure after parsing.
        // The raw text (with comments) is sent directly.

        // Disable button to prevent multiple clicks
        this.disabled = true;
        this.textContent = 'Saving...';
        messageArea.textContent = '';
        messageArea.className = '';


        fetch('/v1/config/models-rules', {
            method: 'POST',
            headers: {
                'Content-Type': 'text/plain', // Send as raw text
            },
            body: rawEditorContent // Send the raw editor content
        })
        .then(response => {
            // Re-enable button regardless of outcome
            this.disabled = false;
            this.textContent = 'Save Configuration';
            return response.json().then(data => ({ status: response.status, body: data }));
        })
        .then(({ status, body }) => {
            if (status === 200) {
                messageArea.textContent = body.message || 'Configuration saved and reloaded successfully!';
                messageArea.className = 'success';
                 // Optionally, refresh editor content from server again if needed
                 // Since we sent raw text, and if successful, the server saved it as is,
                 // the editor content is already up-to-date.
                 // If we wanted to be absolutely sure, we could re-fetch:
                 // fetch('/v1/config/models-rules').then(r => r.text()).then(text => editor.setValue(text));
            } else {
                let errorMessage = `Error saving configuration (HTTP ${status}): `;
                if (body.detail && Array.isArray(body.errors)) { // Pydantic validation errors
                    errorMessage += `${body.detail}. Please check the following issues:\n`;
                    const errorDetails = body.errors.map(err => {
                        const loc = err.loc.join(' -> ');
                        return `- Location: ${loc}, Message: ${err.msg}, Type: ${err.type}`;
                    }).join('\n');
                    messageArea.innerHTML = `<strong>Validation Error (HTTP ${status}):</strong><pre>${body.detail}\n${errorDetails}</pre>`;
                } else if (body.detail) {
                     messageArea.innerHTML = `<strong>Error (HTTP ${status}):</strong><pre>${body.detail}</pre>`;
                } else {
                     messageArea.textContent = errorMessage + (JSON.stringify(body) || "Unknown error");
                }
                messageArea.className = 'error';
            }
        })
        .catch(error => {
            console.error('Error saving configuration:', error);
            messageArea.textContent = 'Error saving configuration: ' + error.message;
            messageArea.className = 'error';
            // Re-enable button in case of network error
            this.disabled = false;
            this.textContent = 'Save Configuration';
        });
    });
});
