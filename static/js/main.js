document.addEventListener('DOMContentLoaded', function() {
    const mainContent = document.getElementById('main-content');
    const navLinks = document.querySelectorAll('.nav-link');
    let logRefreshInterval = null;

    // --- Templates for each section ---
    const templates = {
        tasks: () => `
            <section id="tasks-section" class="content-section">
                <div class="section-header">
                    <h2>Task Management</h2>
                    <button id="add-task-btn" class="control-button primary-btn">➕ Create New Task</button>
                </div>
                <div id="tasks-table-container">
                    <p>Loading task list...</p>
                </div>
            </section>`,
        results: () => `
            <section id="results-section" class="content-section">
                <div class="section-header">
                    <h2>Result Viewer</h2>
                </div>
                <div class="results-filter-bar">
                    <select id="result-file-selector"><option>Loading...</option></select>
                    <label>
                        <input type="checkbox" id="recommended-only-checkbox">
                        AI Recommended Only
                    </label>
                    <select id="sort-by-selector">
                        <option value="crawl_time">By Crawl Time</option>
                        <option value="publish_time">By Publish Time</option>
                        <option value="price">By Price</option>
                    </select>
                    <select id="sort-order-selector">
                        <option value="desc">Descending</option>
                        <option value="asc">Ascending</option>
                    </select>
                    <button id="refresh-results-btn" class="control-button">🔄 Refresh</button>
                </div>
                <div id="results-grid-container">
                    <p>Please select a result file first.</p>
                </div>
            </section>`,
        logs: () => `
            <section id="logs-section" class="content-section">
                <div class="section-header">
                    <h2>Run Logs</h2>
                    <div class="log-controls">
                        <label>
                            <input type="checkbox" id="auto-refresh-logs-checkbox">
                            Auto-refresh
                        </label>
                        <button id="refresh-logs-btn" class="control-button">🔄 Refresh</button>
                        <button id="clear-logs-btn" class="control-button danger-btn">🗑️ Clear Logs</button>
                    </div>
                </div>
                <pre id="log-content-container">Loading logs...</pre>
            </section>`,
        settings: () => `
            <section id="settings-section" class="content-section">
                <h2>System Settings</h2>
                <div class="settings-card">
                    <h3>System Status Check</h3>
                    <div id="system-status-container"><p>Loading status...</p></div>
                </div>
                <div class="settings-card">
                    <h3>Prompt Management</h3>
                    <div class="prompt-manager">
                        <div class="prompt-list-container">
                            <label for="prompt-selector">Select a Prompt to Edit:</label>
                            <select id="prompt-selector"><option>Loading...</option></select>
                        </div>
                        <div class="prompt-editor-container">
                            <textarea id="prompt-editor" spellcheck="false" disabled placeholder="Please select a Prompt file from above to begin editing..."></textarea>
                            <button id="save-prompt-btn" class="control-button primary-btn" disabled>Save Changes</button>
                        </div>
                    </div>
                </div>
            </section>`
    };

    // --- API Functions ---
    async function fetchPrompts() {
        try {
            const response = await fetch('/api/prompts');
            if (!response.ok) throw new Error('Could not fetch prompt list');
            return await response.json();
        } catch (error) {
            console.error(error);
            return [];
        }
    }

    async function fetchPromptContent(filename) {
        try {
            const response = await fetch(`/api/prompts/${filename}`);
            if (!response.ok) throw new Error(`Could not fetch content of prompt file ${filename}`);
            return await response.json();
        } catch (error) {
            console.error(error);
            return null;
        }
    }

    async function updatePrompt(filename, content) {
        try {
            const response = await fetch(`/api/prompts/${filename}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: content }),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to update prompt');
            }
            return await response.json();
        } catch (error) {
            console.error(`Could not update prompt ${filename}:`, error);
            alert(`Error: ${error.message}`);
            return null;
        }
    }

    async function createTaskWithAI(data) {
        try {
            const response = await fetch(`/api/tasks/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to create task with AI');
            }
            console.log(`AI task created successfully!`);
            return await response.json();
        } catch (error) {
            console.error(`Could not create task with AI:`, error);
            alert(`Error: ${error.message}`);
            return null;
        }
    }

    async function deleteTask(taskId) {
        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to delete task');
            }
            console.log(`Task ${taskId} deleted successfully!`);
            return await response.json();
        } catch (error) {
            console.error(`Could not delete task ${taskId}:`, error);
            alert(`Error: ${error.message}`);
            return null;
        }
    }

    async function updateTask(taskId, data) {
        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to update task');
            }
            console.log(`Task ${taskId} updated successfully!`);
            return await response.json();
        } catch (error) {
            console.error(`Could not update task ${taskId}:`, error);
            // TODO: Use a more elegant notification system
            alert(`Error: ${error.message}`);
            return null;
        }
    }

    async function fetchTasks() {
        try {
            const response = await fetch('/api/tasks');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("Could not fetch task list:", error);
            return null;
        }
    }

    async function fetchResultFiles() {
        try {
            const response = await fetch('/api/results/files');
            if (!response.ok) throw new Error('Could not fetch result file list');
            return await response.json();
        } catch (error) {
            console.error(error);
            return null;
        }
    }

    async function fetchResultContent(filename, recommendedOnly, sortBy, sortOrder) {
        try {
            const params = new URLSearchParams({
                page: 1,
                limit: 100, // Fetch a decent number of items
                recommended_only: recommendedOnly,
                sort_by: sortBy,
                sort_order: sortOrder
            });
            const response = await fetch(`/api/results/${filename}?${params}`);
            if (!response.ok) throw new Error(`Could not fetch content of file ${filename}`);
            return await response.json();
        } catch (error) {
            console.error(error);
            return null;
        }
    }

    async function fetchSystemStatus() {
        try {
            const response = await fetch('/api/settings/status');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("Could not fetch system status:", error);
            return null;
        }
    }

    async function clearLogs() {
        try {
            const response = await fetch('/api/logs', { method: 'DELETE' });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to clear logs');
            }
            return await response.json();
        } catch (error) {
            console.error("Could not clear logs:", error);
            alert(`Error: ${error.message}`);
            return null;
        }
    }

    async function fetchLogs(fromPos = 0) {
        try {
            const response = await fetch(`/api/logs?from_pos=${fromPos}`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("Could not fetch logs:", error);
            return { new_content: `\nFailed to load logs: ${error.message}`, new_pos: fromPos };
        }
    }

    // --- Render Functions ---
    function renderSystemStatus(status) {
        if (!status) return '<p>Could not load system status.</p>';

        const renderStatusTag = (isOk) => isOk 
            ? `<span class="tag status-ok">OK</span>`
            : `<span class="tag status-error">Error</span>`;

        const env = status.env_file || {};

        return `
            <ul class="status-list">
                <li class="status-item">
                    <span class="label">Login State File (xianyu_state.json)</span>
                    <span class="value">${renderStatusTag(status.login_state_file && status.login_state_file.exists)}</span>
                </li>
                <li class="status-item">
                    <span class="label">Environment File (.env)</span>
                    <span class="value">${renderStatusTag(env.exists)}</span>
                </li>
                <li class="status-item">
                    <span class="label">OpenAI API Key</span>
                    <span class="value">${renderStatusTag(env.openai_api_key_set)}</span>
                </li>
                <li class="status-item">
                    <span class="label">OpenAI Base URL</span>
                    <span class="value">${renderStatusTag(env.openai_base_url_set)}</span>
                </li>
                <li class="status-item">
                    <span class="label">OpenAI Model Name</span>
                    <span class="value">${renderStatusTag(env.openai_model_name_set)}</span>
                </li>
                <li class="status-item">
                    <span class="label">Ntfy Topic URL</span>
                    <span class="value">${renderStatusTag(env.ntfy_topic_url_set)}</span>
                </li>
            </ul>
        `;
    }

    function renderResultsGrid(data) {
        if (!data || !data.items || data.items.length === 0) {
            return '<p>No item records found matching the criteria.</p>';
        }

        const cards = data.items.map(item => {
            const info = item.item_info || {};
            const seller = item.seller_info || {};
            const ai = item.ai_analysis || {};

            const isRecommended = ai.is_recommended === true;
            const recommendationClass = isRecommended ? 'recommended' : 'not-recommended';
            const recommendationText = isRecommended ? 'Recommended' : (ai.is_recommended === false ? 'Not Recommended' : 'Pending');
            
            const imageUrl = (info.item_image_list && info.item_image_list[0]) ? info.item_image_list[0] : 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
            const crawlTime = item.crawl_time ? new Date(item.crawl_time).toLocaleString('sv-SE').slice(0, 16) : 'Unknown';
            const publishTime = info.publish_time || 'Unknown';

            return `
            <div class="result-card" data-item='${JSON.stringify(item)}'>
                <div class="card-image">
                    <a href="${info.item_link || '#'}" target="_blank"><img src="${imageUrl}" alt="${info.item_title || 'Item Image'}" loading="lazy"></a>
                </div>
                <div class="card-content">
                    <h3 class="card-title"><a href="${info.item_link || '#'}" target="_blank" title="${info.item_title || ''}">${info.item_title || 'No Title'}</a></h3>
                    <p class="card-price">${info.current_price || 'Price Unknown'}</p>
                    <div class="card-ai-summary ${recommendationClass}">
                        <strong>AI Advice: ${recommendationText}</strong>
                        <p title="${ai.reason || ''}">Reason: ${ai.reason || 'No analysis'}</p>
                    </div>
                    <div class="card-footer">
                        <div>
                            <span class="seller-info" title="${info.seller_nickname || seller.seller_nickname || 'Unknown'}">Seller: ${info.seller_nickname || seller.seller_nickname || 'Unknown'}</span>
                            <div class="time-info">
                                <p>Published: ${publishTime}</p>
                                <p>Crawled: ${crawlTime}</p>
                            </div>
                        </div>
                        <a href="${info.item_link || '#'}" target="_blank" class="action-btn">View Details</a>
                    </div>
                </div>
            </div>
            `;
        }).join('');

        return `<div id="results-grid">${cards}</div>`;
    }

    function renderTasksTable(tasks) {
        if (!tasks || tasks.length === 0) {
            return '<p>No tasks found. Please click "Create New Task" in the top right to add one.</p>';
        }

        const tableHeader = `
            <thead>
                <tr>
                    <th>Enabled</th>
                    <th>Task Name</th>
                    <th>Keyword</th>
                    <th>Price Range</th>
                    <th>Filters</th>
                    <th>AI Criteria</th>
                    <th>Actions</th>
                </tr>
            </thead>`;

        const tableBody = tasks.map(task => `
            <tr data-task-id="${task.id}" data-task='${JSON.stringify(task)}'>
                <td>
                    <label class="switch">
                        <input type="checkbox" ${task.enabled ? 'checked' : ''}>
                        <span class="slider round"></span>
                    </label>
                </td>
                <td>${task.task_name}</td>
                <td><span class="tag">${task.keyword}</span></td>
                <td>${task.min_price || 'Any'} - ${task.max_price || 'Any'}</td>
                <td>${task.personal_only ? '<span class="tag personal">Personal Only</span>' : ''}</td>
                <td>${(task.ai_prompt_criteria_file || 'N/A').replace('prompts/', '')}</td>
                <td>
                    <button class="action-btn edit-btn">Edit</button>
                    <button class="action-btn delete-btn">Delete</button>
                </td>
            </tr>`).join('');

        return `<table class="tasks-table">${tableHeader}<tbody>${tableBody}</tbody></table>`;
    }


    async function navigateTo(hash) {
        if (logRefreshInterval) {
            clearInterval(logRefreshInterval);
            logRefreshInterval = null;
        }
        const sectionId = hash.substring(1) || 'tasks';

        // Update nav links active state
        navLinks.forEach(link => {
            link.classList.toggle('active', link.getAttribute('href') === `#${sectionId}`);
        });

        // Update main content
        if (templates[sectionId]) {
            mainContent.innerHTML = templates[sectionId]();
            // Make the new content visible
            const newSection = mainContent.querySelector('.content-section');
            if (newSection) {
                requestAnimationFrame(() => {
                    newSection.classList.add('active');
                });
            }

            // --- Load data for the current section ---
            if (sectionId === 'tasks') {
                const container = document.getElementById('tasks-table-container');
                const tasks = await fetchTasks();
                container.innerHTML = renderTasksTable(tasks);
            } else if (sectionId === 'results') {
                await initializeResultsView();
            } else if (sectionId === 'logs') {
                await initializeLogsView();
            } else if (sectionId === 'settings') {
                await initializeSettingsView();
            }

        } else {
            mainContent.innerHTML = '<section class="content-section active"><h2>Page Not Found</h2></section>';
        }
    }

    async function initializeLogsView() {
        const logContainer = document.getElementById('log-content-container');
        const refreshBtn = document.getElementById('refresh-logs-btn');
        const autoRefreshCheckbox = document.getElementById('auto-refresh-logs-checkbox');
        const clearBtn = document.getElementById('clear-logs-btn');
        let currentLogSize = 0;

        const updateLogs = async (isFullRefresh = false) => {
            // For incremental updates, check if user is at the bottom BEFORE adding new content.
            const shouldAutoScroll = isFullRefresh || (logContainer.scrollHeight - logContainer.clientHeight <= logContainer.scrollTop + 5);

            if (isFullRefresh) {
                currentLogSize = 0;
                logContainer.textContent = 'Loading...';
            }
            
            const logData = await fetchLogs(currentLogSize);

            if (isFullRefresh) {
                // If the log is empty, show a message instead of a blank screen.
                logContainer.textContent = logData.new_content || 'Logs are empty, waiting for content...';
            } else if (logData.new_content) {
                // If it was showing the empty message, replace it.
                if (logContainer.textContent === 'Logs are empty, waiting for content...') {
                    logContainer.textContent = logData.new_content;
                } else {
                    logContainer.textContent += logData.new_content;
                }
            }
            currentLogSize = logData.new_pos;
            
            // Scroll to bottom if it was a full refresh or if the user was already at the bottom.
            if(shouldAutoScroll) {
                logContainer.scrollTop = logContainer.scrollHeight;
            }
        };

        refreshBtn.addEventListener('click', () => updateLogs(true));

        clearBtn.addEventListener('click', async () => {
            if (confirm('Are you sure you want to clear all run logs? This action cannot be undone.')) {
                const result = await clearLogs();
                if (result) {
                    await updateLogs(true);
                    alert('Logs have been cleared.');
                }
            }
        });

        autoRefreshCheckbox.addEventListener('change', () => {
            if (autoRefreshCheckbox.checked) {
                if (logRefreshInterval) clearInterval(logRefreshInterval);
                logRefreshInterval = setInterval(() => updateLogs(false), 1000);
            } else {
                if (logRefreshInterval) {
                    clearInterval(logRefreshInterval);
                    logRefreshInterval = null;
                }
            }
        });

        await updateLogs(true);
    }

    async function fetchAndRenderResults() {
        const selector = document.getElementById('result-file-selector');
        const checkbox = document.getElementById('recommended-only-checkbox');
        const sortBySelector = document.getElementById('sort-by-selector');
        const sortOrderSelector = document.getElementById('sort-order-selector');
        const container = document.getElementById('results-grid-container');

        if (!selector || !checkbox || !container || !sortBySelector || !sortOrderSelector) return;

        const selectedFile = selector.value;
        const recommendedOnly = checkbox.checked;
        const sortBy = sortBySelector.value;
        const sortOrder = sortOrderSelector.value;

        if (!selectedFile) {
            container.innerHTML = '<p>Please select a result file first.</p>';
            return;
        }

        localStorage.setItem('lastSelectedResultFile', selectedFile);

        container.innerHTML = '<p>Loading results...</p>';
        const data = await fetchResultContent(selectedFile, recommendedOnly, sortBy, sortOrder);
        container.innerHTML = renderResultsGrid(data);
    }

    async function initializeResultsView() {
        const selector = document.getElementById('result-file-selector');
        const checkbox = document.getElementById('recommended-only-checkbox');
        const refreshBtn = document.getElementById('refresh-results-btn');
        const sortBySelector = document.getElementById('sort-by-selector');
        const sortOrderSelector = document.getElementById('sort-order-selector');

        const fileData = await fetchResultFiles();
        if (fileData && fileData.files && fileData.files.length > 0) {
            const lastSelectedFile = localStorage.getItem('lastSelectedResultFile');
            // Determine the file to select. Default to the first file if nothing is stored or if the stored file no longer exists.
            let fileToSelect = fileData.files[0];
            if (lastSelectedFile && fileData.files.includes(lastSelectedFile)) {
                fileToSelect = lastSelectedFile;
            }

            selector.innerHTML = fileData.files.map(f =>
                `<option value="${f}" ${f === fileToSelect ? 'selected' : ''}>${f}</option>`
            ).join('');

            // The selector's value is now correctly set by the 'selected' attribute.
            // We can proceed with adding listeners and the initial fetch.

            selector.addEventListener('change', fetchAndRenderResults);
            checkbox.addEventListener('change', fetchAndRenderResults);
            sortBySelector.addEventListener('change', fetchAndRenderResults);
            sortOrderSelector.addEventListener('change', fetchAndRenderResults);
            refreshBtn.addEventListener('click', fetchAndRenderResults);
            // Initial load
            await fetchAndRenderResults();
        } else {
            selector.innerHTML = '<option value="">No result files available</option>';
            document.getElementById('results-grid-container').innerHTML = '<p>No result files found. Please run a monitoring task first.</p>';
        }
    }

    async function initializeSettingsView() {
        // 1. Render System Status
        const statusContainer = document.getElementById('system-status-container');
        const status = await fetchSystemStatus();
        statusContainer.innerHTML = renderSystemStatus(status);

        // 2. Setup Prompt Editor
        const promptSelector = document.getElementById('prompt-selector');
        const promptEditor = document.getElementById('prompt-editor');
        const savePromptBtn = document.getElementById('save-prompt-btn');

        const prompts = await fetchPrompts();
        if (prompts && prompts.length > 0) {
            promptSelector.innerHTML = '<option value="">-- Please Select --</option>' + prompts.map(p => `<option value="${p}">${p}</option>`).join('');
        } else {
            promptSelector.innerHTML = '<option value="">No Prompt files found</option>';
        }

        promptSelector.addEventListener('change', async () => {
            const selectedFile = promptSelector.value;
            if (selectedFile) {
                promptEditor.value = "Loading...";
                promptEditor.disabled = true;
                savePromptBtn.disabled = true;
                const data = await fetchPromptContent(selectedFile);
                if (data) {
                    promptEditor.value = data.content;
                    promptEditor.disabled = false;
                    savePromptBtn.disabled = false;
                } else {
                    promptEditor.value = `Failed to load file ${selectedFile}.`;
                }
            } else {
                promptEditor.value = "Please select a Prompt file from above to begin editing...";
                promptEditor.disabled = true;
                savePromptBtn.disabled = true;
            }
        });

        savePromptBtn.addEventListener('click', async () => {
            const selectedFile = promptSelector.value;
            const content = promptEditor.value;
            if (!selectedFile) {
                alert("Please select a Prompt file to save first.");
                return;
            }

            savePromptBtn.disabled = true;
            savePromptBtn.textContent = 'Saving...';

            const result = await updatePrompt(selectedFile, content);
            if (result) {
                alert(result.message || "Saved successfully!");
            }
            // No need to show alert on failure, as updatePrompt already does.
            
            savePromptBtn.disabled = false;
            savePromptBtn.textContent = 'Save Changes';
        });
    }

    // Handle navigation clicks
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const hash = this.getAttribute('href');
            if (window.location.hash !== hash) {
                window.location.hash = hash;
            }
        });
    });

    // Handle hash changes (e.g., back/forward buttons, direct URL)
    window.addEventListener('hashchange', () => {
        navigateTo(window.location.hash);
    });

    // --- Event Delegation for dynamic content ---
    mainContent.addEventListener('click', async (event) => {
        const target = event.target;
        const button = target.closest('button'); // Find the closest button element
        if (!button) return;

        const row = button.closest('tr');
        const taskId = row ? row.dataset.taskId : null;

        if (button.matches('.view-json-btn')) {
            const card = button.closest('.result-card');
            const itemData = JSON.parse(card.dataset.item);
            const jsonContent = document.getElementById('json-viewer-content');
            jsonContent.textContent = JSON.stringify(itemData, null, 2);
            
            const modal = document.getElementById('json-viewer-modal');
            modal.style.display = 'flex';
            setTimeout(() => modal.classList.add('visible'), 10);
        } else if (button.matches('.edit-btn')) {
            const taskData = JSON.parse(row.dataset.task);
            
            row.classList.add('editing');
            row.innerHTML = `
                <td>
                    <label class="switch">
                        <input type="checkbox" ${taskData.enabled ? 'checked' : ''} data-field="enabled">
                        <span class="slider round"></span>
                    </label>
                </td>
                <td><input type="text" value="${taskData.task_name}" data-field="task_name"></td>
                <td><input type="text" value="${taskData.keyword}" data-field="keyword"></td>
                <td>
                    <input type="text" value="${taskData.min_price || ''}" placeholder="Any" data-field="min_price" style="width: 60px;"> -
                    <input type="text" value="${taskData.max_price || ''}" placeholder="Any" data-field="max_price" style="width: 60px;">
                </td>
                <td>
                    <label>
                        <input type="checkbox" ${taskData.personal_only ? 'checked' : ''} data-field="personal_only"> Personal Only
                    </label>
                </td>
                <td>${(taskData.ai_prompt_criteria_file || 'N/A').replace('prompts/', '')}</td>
                <td>
                    <button class="action-btn save-btn">Save</button>
                    <button class="action-btn cancel-btn">Cancel</button>
                </td>
            `;

        } else if (button.matches('.delete-btn')) {
            const taskName = row.querySelector('td:nth-child(2)').textContent;
            if (confirm(`Are you sure you want to delete the task "${taskName}"?`)) {
                const result = await deleteTask(taskId);
                if (result) {
                    row.remove();
                }
            }
        } else if (button.matches('#add-task-btn')) {
            const modal = document.getElementById('add-task-modal');
            modal.style.display = 'flex';
            // Use a short timeout to allow the display property to apply before adding the transition class
            setTimeout(() => modal.classList.add('visible'), 10);
        } else if (button.matches('.save-btn')) {
            const taskNameInput = row.querySelector('input[data-field="task_name"]');
            const keywordInput = row.querySelector('input[data-field="keyword"]');
            if (!taskNameInput.value.trim() || !keywordInput.value.trim()) {
                alert('Task Name and Keyword cannot be empty.');
                return;
            }

            const inputs = row.querySelectorAll('input[data-field]');
            const updatedData = {};
            inputs.forEach(input => {
                const field = input.dataset.field;
                if (input.type === 'checkbox') {
                    updatedData[field] = input.checked;
                } else {
                    updatedData[field] = input.value.trim() === '' ? null : input.value.trim();
                }
            });

            const result = await updateTask(taskId, updatedData);
            if (result && result.task) {
                const container = document.getElementById('tasks-table-container');
                const tasks = await fetchTasks();
                container.innerHTML = renderTasksTable(tasks);
            }
        } else if (button.matches('.cancel-btn')) {
            const container = document.getElementById('tasks-table-container');
            const tasks = await fetchTasks();
            container.innerHTML = renderTasksTable(tasks);
        }
    });

    mainContent.addEventListener('change', async (event) => {
        const target = event.target;
        // Check if the changed element is a toggle switch in the main table (not in an editing row)
        if (target.matches('.tasks-table input[type="checkbox"]') && !target.closest('tr.editing')) {
            const row = target.closest('tr');
            const taskId = row.dataset.taskId;
            const isEnabled = target.checked;

            if (taskId) {
                await updateTask(taskId, { enabled: isEnabled });
                // The visual state is already updated by the checkbox itself.
            }
        }
    });

    // --- Modal Logic ---
    const modal = document.getElementById('add-task-modal');
    if (modal) {
        const closeModalBtn = document.getElementById('close-modal-btn');
        const cancelBtn = document.getElementById('cancel-add-task-btn');
        const saveBtn = document.getElementById('save-new-task-btn');
        const form = document.getElementById('add-task-form');

        const closeModal = () => {
            modal.classList.remove('visible');
            setTimeout(() => {
                modal.style.display = 'none';
                form.reset(); // Reset form on close
            }, 300);
        };

        closeModalBtn.addEventListener('click', closeModal);
        cancelBtn.addEventListener('click', closeModal);
        modal.addEventListener('click', (event) => {
            // Close if clicked on the overlay background
            if (event.target === modal) {
                closeModal();
            }
        });

        saveBtn.addEventListener('click', async () => {
            if (form.checkValidity() === false) {
                form.reportValidity();
                return;
            }

            const formData = new FormData(form);
            const data = {
                task_name: formData.get('task_name'),
                keyword: formData.get('keyword'),
                description: formData.get('description'),
                min_price: formData.get('min_price') || null,
                max_price: formData.get('max_price') || null,
                personal_only: formData.get('personal_only') === 'on',
            };

            // Show loading state
            const btnText = saveBtn.querySelector('.btn-text');
            const spinner = saveBtn.querySelector('.spinner');
            btnText.style.display = 'none';
            spinner.style.display = 'inline-block';
            saveBtn.disabled = true;

            const result = await createTaskWithAI(data);

            // Hide loading state
            btnText.style.display = 'inline-block';
            spinner.style.display = 'none';
            saveBtn.disabled = false;

            if (result && result.task) {
                closeModal();
                // Refresh task list
                const container = document.getElementById('tasks-table-container');
                if (container) {
                    const tasks = await fetchTasks();
                    container.innerHTML = renderTasksTable(tasks);
                }
            }
        });
    }


    // --- Header Controls & Status ---
    function updateHeaderControls(status) {
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');
        const startBtn = document.getElementById('start-all-tasks');
        const stopBtn = document.getElementById('stop-all-tasks');

        // Reset buttons state
        startBtn.disabled = false;
        startBtn.innerHTML = `🚀 Start All`;
        stopBtn.disabled = false;
        stopBtn.innerHTML = `🛑 Stop All`;

        if (status && status.scraper_running) {
            statusIndicator.className = 'status-running';
            statusText.textContent = 'Running';
            startBtn.style.display = 'none';
            stopBtn.style.display = 'inline-block';
        } else {
            statusIndicator.className = 'status-stopped';
            statusText.textContent = 'Stopped';
            startBtn.style.display = 'inline-block';
            stopBtn.style.display = 'none';
        }
    }

    async function refreshSystemStatus() {
        const status = await fetchSystemStatus();
        updateHeaderControls(status);
    }

    document.getElementById('start-all-tasks').addEventListener('click', async () => {
        const btn = document.getElementById('start-all-tasks');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="vertical-align: middle;"></span> Starting...`;

        try {
            const response = await fetch('/api/tasks/start-all', { method: 'POST' });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to start');
            }
            await response.json();
            // Give backend a moment to update state before refreshing
            setTimeout(refreshSystemStatus, 1000);
        } catch (error) {
            alert(`Failed to start tasks: ${error.message}`);
            await refreshSystemStatus(); // Refresh status to reset button state
        }
    });

    document.getElementById('stop-all-tasks').addEventListener('click', async () => {
        const btn = document.getElementById('stop-all-tasks');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="vertical-align: middle;"></span> Stopping...`;

        try {
            const response = await fetch('/api/tasks/stop-all', { method: 'POST' });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to stop');
            }
            await response.json();
            setTimeout(refreshSystemStatus, 1000);
        } catch (error) {
            alert(`Failed to stop tasks: ${error.message}`);
            await refreshSystemStatus(); // Refresh status to reset button state
        }
    });

    // Initial load
    navigateTo(window.location.hash || '#tasks');
    refreshSystemStatus();

    // --- JSON Viewer Modal Logic ---
    const jsonViewerModal = document.getElementById('json-viewer-modal');
    if (jsonViewerModal) {
        const closeBtn = document.getElementById('close-json-viewer-btn');
        
        const closeModal = () => {
            jsonViewerModal.classList.remove('visible');
            setTimeout(() => {
                jsonViewerModal.style.display = 'none';
            }, 300);
        };

        closeBtn.addEventListener('click', closeModal);
        jsonViewerModal.addEventListener('click', (event) => {
            if (event.target === jsonViewerModal) {
                closeModal();
            }
        });
    }
});
