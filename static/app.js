// State
let appState = {
    gameData: null,
    steamGameData: null,
    selectedImages: { grid: "", hero: "", icon: "" },
    selectedTags: new Set(),
    editMode: false,
    existingPageId: null,
    existingPageUrl: null,
    notionGameProps: null,
    config: {
        field_mapping: {},
        use_hero_cover: true,
        use_icon_icon: true,
        database_id: ""
    },
    notionProperties: {}
};

// 在途查重请求：提交前若查重尚未返回，必须先等它结束，避免在"已存在"的情况下重复建页
let pendingExistenceCheck = null;

// DOM Elements
const els = {
    searchInput: document.getElementById('search-input'),
    searchBtn: document.getElementById('search-btn'),
    loadingOverlay: document.getElementById('main-loading'),
    gameInfoSection: document.getElementById('game-info-section'),
    gallerySection: document.getElementById('image-gallery-section'),
    submitSection: document.getElementById('submit-section'),
    submitBtn: document.getElementById('submit-btn'),
    
    // Forms
    title: document.getElementById('game-title'),
    titleEn: document.getElementById('game-title-en'),
    developer: document.getElementById('game-developer'),
    publisher: document.getElementById('game-publisher'),
    releaseDate: document.getElementById('game-release-date'),
    playtime: document.getElementById('game-playtime'),
    refreshPlaytimeBtn: document.getElementById('refresh-playtime-btn'),
    steamUrl: document.getElementById('game-steam-url'),
    description: document.getElementById('game-description'),
    genresContainer: document.getElementById('genres-container'),
    addGenreInput: document.getElementById('add-genre-input'),
    tagsContainer: document.getElementById('tags-container'),
    addTagInput: document.getElementById('add-tag-input'),
    headerImage: document.getElementById('game-header-image'),

    // Edit Mode Banner & Actions
    editBanner: document.getElementById('edit-banner'),
    editBannerLink: document.getElementById('edit-banner-view-link'),
    btnForceCreate: document.getElementById('btn-force-create'),
    btnResetToSteam: document.getElementById('btn-reset-to-steam'),
    createBtnGroup: document.getElementById('create-btn-group'),
    editBtnGroup: document.getElementById('edit-btn-group'),
    updateImagesBtn: document.getElementById('update-images-btn'),
    updateAllBtn: document.getElementById('update-all-btn'),

    // Galleries
    tabs: document.querySelectorAll('.tab-btn'),
    galleries: {
        grids: document.getElementById('gallery-grids'),
        heroes: document.getElementById('gallery-heroes'),
        icons: document.getElementById('gallery-icons')
    },

    // Settings Modal
    settingsBtn: document.getElementById('open-settings-btn'),
    modal: document.getElementById('settings-modal'),
    closeBtn: document.getElementById('close-settings-btn'),
    notionToken: document.getElementById('notion-token'),
    sgdbKey: document.getElementById('sgdb-key'),
    steamApiKey: document.getElementById('steam-api-key'),
    steamId64: document.getElementById('steam-id64'),
    proxyUrl: document.getElementById('proxy-url'),
    saveKeysBtn: document.getElementById('save-keys-btn'),
    fetchDbsBtn: document.getElementById('fetch-dbs-btn'),
    dbSelect: document.getElementById('db-select'),
    mappingTableBody: document.querySelector('#mapping-table tbody'),
    useHeroCover: document.getElementById('use-hero-cover'),
    useIconIcon: document.getElementById('use-icon-icon'),
    saveConfigBtn: document.getElementById('save-config-btn'),
    
    toastContainer: document.getElementById('toast-container'),
    searchResults: document.getElementById('search-results')
};

const DEFAULT_FIELDS = [
    { key: 'title', label: '游戏名称', type: ['title', 'rich_text', 'select'], aliases: ['游戏名称', '名称', '名字', 'title', 'name', 'game'] },
    { key: 'title_en', label: '英文全名', type: ['title', 'rich_text', 'select'], aliases: ['全名', '英文全名', '英文名', 'title_en', 'english name', 'english title', '原名'] },
    { key: 'cover_grid', label: 'Grid封面', type: ['files'], aliases: ['封面', 'cover', 'grid', '海报', '封面图', 'grid封面', 'boxart'] },
    { key: 'genre', label: '类型', type: ['multi_select', 'select'], aliases: ['类型', '分类', 'genre', 'genres', '游戏类型', '类别'] },
    { key: 'tags', label: '标签', type: ['multi_select', 'select', 'rich_text'], aliases: ['标签', 'tags', 'tag', '游戏标签', 'steam标签', 'steam tags', 'user tags'] },
    { key: 'release_date', label: '发行日期', type: ['date'], aliases: ['发行日期', '发售日期', 'date', 'release date', 'release_date', '日期', '上线时间'] },
    { key: 'playtime', label: '游玩时长(小时)', type: ['number', 'rich_text', 'select'], aliases: ['游玩时长', '时长', 'playtime', 'play time', 'hours', '游戏时长', '游玩时间'] },
    { key: 'developer', label: '开发商', type: ['rich_text', 'select', 'multi_select'], aliases: ['开发商', 'developer', 'developers', '开发团队', '制作组', '开发', 'dev'] },
    { key: 'publisher', label: '发行商', type: ['rich_text', 'select', 'multi_select'], aliases: ['发行商', 'publisher', 'publishers', '发行', 'pub'] },
    { key: 'description', label: '简介', type: ['rich_text'], aliases: ['简介', 'description', 'desc', '描述', '游戏简介', '详情'] },
    { key: 'steam_url', label: 'Steam链接', type: ['url', 'rich_text'], aliases: ['steam链接', 'steam_url', 'steam url', '链接', 'url', 'link', 'steam'] }
];

// Clear autofilled admin if browser password manager erroneously fills it
function clearAutofilledAdmin() {
    if (els.searchInput && (els.searchInput.value.toLowerCase() === 'admin' || els.searchInput.value.trim() === 'admin')) {
        els.searchInput.value = '';
    }
}

// Init
function initElements() {
    els.playtime = document.getElementById('game-playtime');
    els.refreshPlaytimeBtn = document.getElementById('refresh-playtime-btn');
    els.steamApiKey = document.getElementById('steam-api-key');
    els.steamId64 = document.getElementById('steam-id64');
    els.tagsContainer = document.getElementById('tags-container');
    els.addTagInput = document.getElementById('add-tag-input');
    els.genresContainer = document.getElementById('genres-container');
    els.addGenreInput = document.getElementById('add-genre-input');

    els.editBanner = document.getElementById('edit-banner');
    els.editBannerLink = document.getElementById('edit-banner-view-link');
    els.btnForceCreate = document.getElementById('btn-force-create');
    els.btnResetToSteam = document.getElementById('btn-reset-to-steam');
    els.createBtnGroup = document.getElementById('create-btn-group');
    els.editBtnGroup = document.getElementById('edit-btn-group');
    els.updateImagesBtn = document.getElementById('update-images-btn');
    els.updateAllBtn = document.getElementById('update-all-btn');
}

document.addEventListener('DOMContentLoaded', async () => {
    initElements();
    clearAutofilledAdmin();
    bindEvents();
    await loadConfig();
    clearAutofilledAdmin();
});

window.addEventListener('load', () => {
    clearAutofilledAdmin();
    setTimeout(clearAutofilledAdmin, 50);
    setTimeout(clearAutofilledAdmin, 150);
    setTimeout(clearAutofilledAdmin, 300);
    setTimeout(clearAutofilledAdmin, 600);
});

// Unicode Decoder Helper
function decodeUnicodeString(str) {
    if (!str || typeof str !== 'string') return str;
    if (str.includes('\\u') || str.includes('\\U')) {
        try {
            return JSON.parse(`"${str}"`);
        } catch (e) {
            return str.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
        }
    }
    return str;
}

// Toast System
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    // Support links in toast
    toast.innerHTML = message;
    els.toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Events
function bindEvents() {
    els.searchInput.addEventListener('focus', clearAutofilledAdmin);
    els.searchInput.addEventListener('input', clearAutofilledAdmin);
    els.searchBtn.addEventListener('click', handleSearch);
    els.searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSearch();
    });

    els.addGenreInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const val = e.target.value.trim();
            if (val) {
                if (!appState.gameData.genres) appState.gameData.genres = [];
                appState.gameData.genres.push(val);
                renderGenres();
                e.target.value = '';
            }
        }
    });

    els.addTagInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const val = e.target.value.trim();
            if (val) {
                if (!appState.gameData) appState.gameData = {};
                if (!appState.gameData.tags) appState.gameData.tags = [];
                if (!appState.gameData.tags.includes(val)) {
                    appState.gameData.tags.push(val);
                }
                if (!appState.selectedTags) appState.selectedTags = new Set();
                appState.selectedTags.add(val);
                renderTags();
                e.target.value = '';
            }
        }
    });

    const btnPick5 = document.getElementById('tags-pick-5');
    if (btnPick5) {
        btnPick5.addEventListener('click', () => {
            if (appState.gameData && appState.gameData.tags) {
                appState.selectedTags = new Set(appState.gameData.tags.slice(0, 5));
                renderTags();
            }
        });
    }
    const btnPickAll = document.getElementById('tags-pick-all');
    if (btnPickAll) {
        btnPickAll.addEventListener('click', () => {
            if (appState.gameData && appState.gameData.tags) {
                appState.selectedTags = new Set(appState.gameData.tags);
                renderTags();
            }
        });
    }
    const btnClearAll = document.getElementById('tags-clear-all');
    if (btnClearAll) {
        btnClearAll.addEventListener('click', () => {
            if (appState.selectedTags) {
                appState.selectedTags.clear();
                renderTags();
            }
        });
    }

    els.tabs.forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    document.querySelectorAll('.sub-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.sub-filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            applyGridOrientationFilter(btn.dataset.orientation);
        });
    });

    els.submitBtn.addEventListener('click', handleSubmit);

    if (els.btnForceCreate) {
        els.btnForceCreate.addEventListener('click', () => {
            exitEditMode();
            if (appState.steamGameData) {
                appState.gameData = JSON.parse(JSON.stringify(appState.steamGameData));
                appState.selectedTags = new Set((appState.gameData.tags || []).slice(0, 5));
                populateGameForm();
            }
            showToast('已切换为强制新建模式，将创建新的 Notion 页面', 'info');
        });
    }

    if (els.btnResetToSteam) {
        els.btnResetToSteam.addEventListener('click', () => {
            if (appState.steamGameData) {
                appState.gameData = JSON.parse(JSON.stringify(appState.steamGameData));
                appState.selectedTags = new Set((appState.gameData.tags || []).slice(0, 5));
                populateGameForm();
                showToast('已使用 Steam 原始数据覆盖当前表单', 'info');
            }
        });
    }

    if (els.updateImagesBtn) {
        els.updateImagesBtn.addEventListener('click', () => handleUpdate(true));
    }

    if (els.updateAllBtn) {
        els.updateAllBtn.addEventListener('click', () => handleUpdate(false));
    }

    // Settings
    els.settingsBtn.addEventListener('click', () => {
        loadConfig();
        els.modal.classList.remove('hidden');
    });
    els.closeBtn.addEventListener('click', () => els.modal.classList.add('hidden'));
    
    document.querySelectorAll('.toggle-password').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const btnEl = e.currentTarget || e.target;
            const input = document.getElementById(btnEl.dataset.target);
            if (!input) return;
            const willShow = input.type === 'password';
            input.type = willShow ? 'text' : 'password';
            // 文字标签跟随状态变化（原为 👁️ 图标，用户反馈图标观感差，改为"显示/隐藏"）
            btnEl.textContent = willShow ? '隐藏' : '显示';
            btnEl.title = willShow ? '隐藏内容' : '显示内容';
        });
    });

    els.saveKeysBtn.addEventListener('click', saveApiKeys);
    els.fetchDbsBtn.addEventListener('click', fetchDatabases);
    els.dbSelect.addEventListener('change', onDatabaseSelect);
    els.saveConfigBtn.addEventListener('click', saveConfig);

    if (els.refreshPlaytimeBtn) {
        els.refreshPlaytimeBtn.addEventListener('click', handleRefreshPlaytime);
    }
}

async function handleRefreshPlaytime() {
    if (!appState.gameData || !appState.gameData.app_id) {
        showToast('请先检索或选择游戏', 'info');
        return;
    }
    els.refreshPlaytimeBtn.disabled = true;
    els.refreshPlaytimeBtn.textContent = '⏳';
    try {
        const res = await fetch(`/api/steam/${appState.gameData.app_id}/playtime`);
        if (!res.ok) throw new Error('时长查询请求失败');
        const data = await res.json();
        if (data.playtime !== null && data.playtime !== undefined) {
            els.playtime.value = data.playtime;
            appState.gameData.playtime = data.playtime;
            showToast(`已获取到游玩时长: ${data.playtime} 小时`, 'success');
        } else {
            els.playtime.placeholder = '可直接手动输入时长 (小时)';
            showToast('未能自动获取到时长（家庭共享借阅游戏或网络超时，可直接在此手动填入小时数）', 'warning');
        }
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        els.refreshPlaytimeBtn.disabled = false;
        els.refreshPlaytimeBtn.textContent = '🔄';
    }
}

// --- Main Flow ---

async function handleSearch() {
    const input = els.searchInput.value.trim();
    if (!input) return;

    // Extract App ID from URL
    const urlMatch = input.match(/app\/(\d+)/);
    if (urlMatch) {
        return fetchGameById(urlMatch[1]);
    }

    // Pure numeric = direct App ID
    if (/^\d+$/.test(input)) {
        return fetchGameById(input);
    }

    // Direct selection with App ID like "Game Name (1325200)"
    const parenMatch = input.match(/\((\d{2,10})\)\s*$/);
    if (parenMatch) {
        return fetchGameById(parenMatch[1]);
    }

    // Otherwise: search by name
    els.searchBtn.disabled = true;
    els.searchBtn.textContent = '搜索中...';
    try {
        const res = await fetch(`/api/steam/search?q=${encodeURIComponent(input)}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || '搜索请求失败，请稍后重试');
        }
        const data = await res.json();
        
        if (!data.results || data.results.length === 0) {
            showToast('未找到匹配的游戏，可直接输入 App ID 或商店链接', 'info');
            return;
        }

        // Show dropdown
        renderSearchResults(data.results);
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        els.searchBtn.disabled = false;
        els.searchBtn.textContent = '搜索';
    }
}

function renderSearchResults(results) {
    els.searchResults.innerHTML = '';
    results.forEach(item => {
        const div = document.createElement('div');
        div.className = 'search-result-item';
        div.innerHTML = `
            <img src="${item.icon || ''}" alt="" onerror="this.style.display='none'">
            <div class="result-info">
                <div class="result-name">${item.name}</div>
                <div class="result-id">App ID: ${item.app_id}</div>
            </div>
        `;
        div.addEventListener('click', () => {
            els.searchResults.classList.add('hidden');
            els.searchInput.value = `${item.name} (${item.app_id})`;
            fetchGameById(String(item.app_id));
        });
        els.searchResults.appendChild(div);
    });
    els.searchResults.classList.remove('hidden');
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrapper')) {
        els.searchResults.classList.add('hidden');
    }
});

function getImageKey(type) {
    if (type === 'heroes') return 'hero';
    if (type === 'grids') return 'grid';
    if (type === 'icons') return 'icon';
    return type.replace(/s$/, '');
}

async function fetchGameById(appId) {
    setLoading(true);
    resetState();
    els.searchResults.classList.add('hidden');

    try {
        // 1. Fetch Steam Data
        const steamRes = await fetch(`/api/steam/${appId}`);
        if (!steamRes.ok) {
            const err = await steamRes.json().catch(() => ({}));
            throw new Error(err.detail || 'Steam data fetch failed');
        }
        const steamData = await steamRes.json();
        if (steamData.tags && Array.isArray(steamData.tags)) {
            steamData.tags = Array.from(new Set(steamData.tags.map(decodeUnicodeString).filter(t => t && t !== '+')));
        }
        appState.steamGameData = JSON.parse(JSON.stringify(steamData));
        appState.gameData = steamData;
        const allTags = steamData.tags || [];
        appState.selectedTags = new Set(allTags.slice(0, 5));
        populateGameForm();
        exitEditMode();

        // 异步查询该游戏是否已存在于 Notion 中（提交前会等待该请求，避免重复建页）
        pendingExistenceCheck = checkNotionExistence(steamData).finally(() => { pendingExistenceCheck = null; });

        // Prepare Steam Official Images as primary/fallback options
        // 桌面图标 = clienticon, 库横幅 = pagecover (hero), Steam封面 = 封面 (grid)
        const steamImgs = steamData.steam_images || {};
        const officialGrids = [];
        if (steamImgs.header || steamData.header_image) {
            officialGrids.push({
                url: steamImgs.header || steamData.header_image,
                thumb: steamImgs.header || steamData.header_image,
                width: 460,
                height: 215,
                style: 'Steam 封面'
            });
        }
        if (steamImgs.library_grid) {
            officialGrids.push({
                url: steamImgs.library_grid,
                thumb: steamImgs.library_grid,
                width: 600,
                height: 900,
                style: 'Steam 库竖版封面'
            });
        }

        const officialHeroes = [];
        if (steamImgs.library_hero) {
            officialHeroes.push({
                url: steamImgs.library_hero,
                thumb: steamImgs.library_hero,
                width: 1920,
                height: 620,
                style: 'Steam 库横幅'
            });
        }

        const officialIcons = [];
        // 1. 最优先：Steam 客户端桌面图标 (clienticon.ico) - 真正的大图标 / 桌面图标
        if (steamImgs.clienticon) {
            officialIcons.push({
                url: steamImgs.clienticon,
                thumb: steamImgs.clienticon,
                style: 'Steam 桌面图标 (clienticon)'
            });
        }

        // 2. Steam 官方高清透明 Logo (logo.png / logo_2x.png)
        if (steamImgs.official_logo) {
            officialIcons.push({
                url: steamImgs.official_logo,
                thumb: steamImgs.official_logo,
                width: 640,
                height: 360,
                isLogo: true,
                style: 'Steam 官方高清透明 Logo'
            });
        }

        // 3. Steam 社区小图标 (icon.jpg)
        if (steamImgs.icon && steamImgs.icon !== steamImgs.clienticon) {
            officialIcons.push({
                url: steamImgs.icon,
                thumb: steamImgs.icon,
                style: 'Steam 社区小图标 (icon)'
            });
        }

        // Set default selection to Steam official images (桌面图标 clienticon 优先默认选中)
        appState.selectedImages = {
            grid: officialGrids.length > 0 ? officialGrids[0].url : "",
            hero: officialHeroes.length > 0 ? officialHeroes[0].url : "",
            icon: officialIcons.length > 0 ? officialIcons[0].url : ""
        };

        // 2. Fetch SGDB Images
        let fetchedGrids = [];
        let fetchedHeroes = [];
        let fetchedIcons = [];
        try {
            const sgdbSearchRes = await fetch(`/api/steamgriddb/search/${appId}`);
            const sgdbSearch = await sgdbSearchRes.json();
            
            if (sgdbSearch.success && sgdbSearch.data && sgdbSearch.data.id) {
                const sgdbId = sgdbSearch.data.id;
                
                const [gridsRes, heroesRes, iconsRes] = await Promise.all([
                    fetch(`/api/steamgriddb/grids/${sgdbId}`).then(r => r.json()).catch(() => ({})),
                    fetch(`/api/steamgriddb/heroes/${sgdbId}`).then(r => r.json()).catch(() => ({})),
                    fetch(`/api/steamgriddb/icons/${sgdbId}`).then(r => r.json()).catch(() => ({}))
                ]);

                fetchedGrids = gridsRes.success ? (gridsRes.data || []) : [];
                fetchedHeroes = heroesRes.success ? (heroesRes.data || []) : [];
                fetchedIcons = iconsRes.success ? (iconsRes.data || []) : [];
            } else {
                showToast('SteamGridDB 未找到此游戏图片，已自动选用 Steam 官方图片', 'info');
            }
        } catch (sgdbErr) {
            showToast('SteamGridDB 获取失败，已自动选用 Steam 官方图片', 'info');
        }

        // 封面 (Grids) 横版绝对优先排序：
        // 1. 所有横版图（官方横版 460x215 + SteamGridDB 92:43 高清横版 920x430 等）排在最前
        // 2. 所有竖版图（官方竖版 600x900 + SteamGridDB 600x900 等）排在后
        const allGrids = [...officialGrids, ...fetchedGrids];
        const horizontalGrids = allGrids.filter(g => g.width && g.height && g.width > g.height);
        const verticalGrids = allGrids.filter(g => !g.width || !g.height || g.width <= g.height);
        const sortedGrids = [...horizontalGrids, ...verticalGrids];

        // 默认选中封面：优先选择第一张横版图！
        if (horizontalGrids.length > 0) {
            appState.selectedImages.grid = horizontalGrids[0].url;
        } else if (sortedGrids.length > 0) {
            appState.selectedImages.grid = sortedGrids[0].url;
        }

        updateGridFilterCounts(horizontalGrids.length, verticalGrids.length);

        renderGallery('grids', sortedGrids);
        renderGallery('heroes', [...officialHeroes, ...fetchedHeroes]);
        renderGallery('icons', [...officialIcons, ...fetchedIcons]);

        els.gameInfoSection.classList.remove('hidden');
        els.gallerySection.classList.remove('hidden');
        els.submitSection.classList.remove('hidden');

    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        setLoading(false);
    }
}

function setLoading(isLoading) {
    els.searchBtn.disabled = isLoading;
    if (isLoading) {
        els.loadingOverlay.classList.remove('hidden');
        els.gameInfoSection.classList.add('hidden');
        els.gallerySection.classList.add('hidden');
        els.submitSection.classList.add('hidden');
    } else {
        els.loadingOverlay.classList.add('hidden');
    }
}

function resetState() {
    appState.selectedImages = { grid: "", hero: "", icon: "" };
}

function populateGameForm() {
    const d = appState.gameData;
    els.title.value = d.title || '';
    els.titleEn.value = d.title_en || '';
    els.developer.value = (d.developers || []).join(', ');
    els.publisher.value = (d.publishers || []).join(', ');
    els.releaseDate.value = d.release_date_iso || '';
    if (els.playtime) {
        if (d.playtime !== undefined && d.playtime !== null) {
            els.playtime.value = d.playtime;
        } else {
            els.playtime.value = '';
            if (appState.rawConfig && appState.rawConfig.steam_api_key_set && appState.rawConfig.steam_id64_set) {
                els.playtime.placeholder = '可手动输入 (家庭库游戏或点🔄重试)';
            } else {
                els.playtime.placeholder = '可手动输入时长 (或在设置中绑定API)';
            }
        }
    }
    els.steamUrl.value = d.steam_url || '';
    els.description.value = d.description || '';
    els.headerImage.src = d.header_image || '';
    
    renderGenres();
    renderTags();
}

function renderGenres() {
    els.genresContainer.innerHTML = '';
    (appState.gameData.genres || []).forEach((genre, idx) => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.innerHTML = `${genre} <span class="tag-remove" data-idx="${idx}">&times;</span>`;
        els.genresContainer.appendChild(tag);
    });

    // Delegate remove events
    els.genresContainer.querySelectorAll('.tag-remove').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(e.target.dataset.idx);
            appState.gameData.genres.splice(idx, 1);
            renderGenres();
        });
    });
}

function renderTags() {
    if (!els.tagsContainer) {
        els.tagsContainer = document.getElementById('tags-container');
    }
    if (!els.tagsContainer) return;
    els.tagsContainer.innerHTML = '';

    if (!appState.gameData) return;
    if (!appState.gameData.tags) appState.gameData.tags = [];
    appState.gameData.tags = Array.from(new Set(appState.gameData.tags.map(decodeUnicodeString).filter(t => t && t !== '+')));
    if (!appState.selectedTags) {
        appState.selectedTags = new Set(appState.gameData.tags.slice(0, 5));
    }

    const allTags = appState.gameData.tags;
    const selectedCount = appState.selectedTags.size;

    const hintEl = document.getElementById('tags-hint');
    if (hintEl) {
        hintEl.textContent = `(点击切换选择，默认前5个，已选 ${selectedCount}/${allTags.length} 个)`;
    }

    allTags.forEach((tagItem, idx) => {
        const isSelected = appState.selectedTags.has(tagItem);
        const tag = document.createElement('span');
        tag.className = `tag ${isSelected ? 'selected' : ''}`;
        tag.title = isSelected ? '点击取消选中' : '点击高亮选中';

        const checkHtml = isSelected ? '<span class="tag-check">✓</span>' : '';
        tag.innerHTML = `${checkHtml}<span class="tag-text">${tagItem}</span><span class="tag-remove" data-idx="${idx}" title="从列表删除">&times;</span>`;

        tag.addEventListener('click', (e) => {
            if (e.target.closest('.tag-remove')) return;
            if (appState.selectedTags.has(tagItem)) {
                appState.selectedTags.delete(tagItem);
            } else {
                appState.selectedTags.add(tagItem);
            }
            renderTags();
        });

        const removeBtn = tag.querySelector('.tag-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                appState.selectedTags.delete(tagItem);
                appState.gameData.tags.splice(idx, 1);
                renderTags();
            });
        }

        els.tagsContainer.appendChild(tag);
    });
}

function switchTab(tabId) {
    els.tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
    Object.values(els.galleries).forEach(g => g.classList.remove('active'));
    els.galleries[tabId].classList.add('active');
    
    // 仅在 Grids 标签页展示封面版式切换器
    const subFilter = document.getElementById('grid-sub-filter');
    if (subFilter) {
        subFilter.style.display = (tabId === 'grids') ? 'flex' : 'none';
    }
}

function updateGridFilterCounts(horizontalCount, verticalCount) {
    const total = horizontalCount + verticalCount;
    const btnAll = document.querySelector('.sub-filter-btn[data-orientation="all"]');
    const btnHoriz = document.querySelector('.sub-filter-btn[data-orientation="horizontal"]');
    const btnVert = document.querySelector('.sub-filter-btn[data-orientation="vertical"]');
    if (btnAll) btnAll.textContent = `全部 (横版优先, ${total})`;
    if (btnHoriz) btnHoriz.textContent = `横版 (92:43, ${horizontalCount})`;
    if (btnVert) btnVert.textContent = `竖版 (600×900, ${verticalCount})`;
}

function applyGridOrientationFilter(orientation) {
    const gridEl = els.galleries.grids;
    gridEl.classList.remove('view-horizontal', 'view-vertical');
    if (orientation === 'horizontal') gridEl.classList.add('view-horizontal');
    if (orientation === 'vertical') gridEl.classList.add('view-vertical');

    gridEl.querySelectorAll('.img-card').forEach(card => {
        const isHorizontal = card.classList.contains('is-horizontal');
        if (orientation === 'all') {
            card.style.display = '';
        } else if (orientation === 'horizontal') {
            card.style.display = isHorizontal ? '' : 'none';
        } else if (orientation === 'vertical') {
            card.style.display = isHorizontal ? 'none' : '';
        }
    });
}

function renderGallery(type, images) {
    const container = els.galleries[type];
    container.innerHTML = '';

    if (!images || images.length === 0) {
        container.innerHTML = '<p class="text-secondary">未找到可用图片 / No images found.</p>';
        return;
    }

    const key = getImageKey(type);
    const currentSelected = appState.selectedImages[key];

    images.forEach(img => {
        const card = document.createElement('div');
        const isSelected = (currentSelected === img.url);
        const isHorizontal = (type === 'grids' && img.width && img.height && img.width > img.height);
        const isLogo = (type === 'icons' && (img.isLogo || (img.width && img.width > img.height * 1.4)));
        
        card.className = `img-card ${isSelected ? 'selected' : ''} ${isHorizontal ? 'is-horizontal' : ''} ${isLogo ? 'is-logo' : ''}`;
        card.dataset.url = img.url;
        card.dataset.horizontal = isHorizontal ? '1' : '0';
        
        const src = img.thumb || img.url;
        const formatBadge = isHorizontal ? '横版 (92:43)' : (type === 'grids' ? '竖版' : (isLogo ? '高清Logo' : ''));
        const styleText = img.style || 'any';
        
        let initialDimension = '';
        if (img.width && img.height) {
            initialDimension = `${img.width}x${img.height}`;
        }
        
        const buildInfoText = (dim) => {
            const parts = [];
            if (dim) parts.push(dim);
            if (formatBadge) parts.push(formatBadge);
            if (styleText && styleText !== 'any') parts.push(styleText);
            return parts.join(' • ') || styleText;
        };
        
        card.innerHTML = `
            <div class="img-thumb-wrap">
                <img src="${src}" loading="lazy" alt="image">
            </div>
            <div class="checkmark">✓</div>
            <div class="img-info">${buildInfoText(initialDimension)}</div>
        `;

        // 动态测量真实分辨率：如果原始没有宽高或属于可能未知的社区图标，加载完毕后用真实尺寸修正显示
        const imgEl = card.querySelector('img');
        imgEl.addEventListener('load', () => {
            if (imgEl.naturalWidth && imgEl.naturalHeight) {
                // 如果之前没有准确尺寸或者尺寸不一致，按真实分辨率更新
                const realDim = `${imgEl.naturalWidth}x${imgEl.naturalHeight}`;
                const infoEl = card.querySelector('.img-info');
                if (infoEl) {
                    infoEl.textContent = buildInfoText(realDim);
                }
            }
        });

        card.addEventListener('click', () => {
            if (appState.selectedImages[key] === img.url) {
                // Toggle off
                card.classList.remove('selected');
                appState.selectedImages[key] = "";
            } else {
                container.querySelectorAll('.img-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                appState.selectedImages[key] = img.url;
            }
        });

        container.appendChild(card);
    });

    // 如果当前处于特定的版式筛选，立即应用过滤
    if (type === 'grids') {
        const activeSubBtn = document.querySelector('.sub-filter-btn.active');
        if (activeSubBtn) {
            applyGridOrientationFilter(activeSubBtn.dataset.orientation);
        }
    }
}

// --- Settings & Config ---

async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        if (res.ok) {
            const data = await res.json();
            appState.rawConfig = data;
            appState.config = {
                database_id: data.database_id || '',
                field_mapping: {},
                use_hero_cover: data.use_hero_as_cover !== false,
                use_icon_icon: data.use_icon_as_page_icon !== false
            };
            
            // Convert backend field_mapping {key: {name, type, enabled}} to frontend format {key: {enabled, property}}
            const backendMapping = data.field_mapping || {};
            for (const [key, val] of Object.entries(backendMapping)) {
                if (val) {
                    appState.config.field_mapping[key] = {
                        enabled: val.enabled !== false,
                        property: val.name || ''
                    };
                }
            }
            
            // Show status in placeholders
            if (data.notion_token_set) {
                els.notionToken.placeholder = `已配置: ${data.notion_token}`;
            } else {
                els.notionToken.placeholder = '输入 Notion Integration Token...';
            }
            if (data.steamgriddb_key_set) {
                els.sgdbKey.placeholder = `已配置: ${data.steamgriddb_key}`;
            } else {
                els.sgdbKey.placeholder = '输入 SteamGridDB API Key (可选)...';
            }
            if (data.steam_api_key_set) {
                els.steamApiKey.placeholder = `已配置: ${data.steam_api_key}`;
            } else {
                els.steamApiKey.placeholder = '用于获取游玩时长 (可选)...';
            }
            if (data.steam_id64) {
                els.steamId64.value = data.steam_id64;
            } else {
                els.steamId64.value = '';
                els.steamId64.placeholder = '76561198xxxxxxxxx (需个人资料游戏详情公开)';
            }
            if (els.proxyUrl) {
                els.proxyUrl.value = data.proxy || '';
            }

            // Try to load DB list if we have a token set
            if (data.notion_token_set && appState.config.database_id) {
                await fetchDatabases();
                els.dbSelect.value = appState.config.database_id;
                await onDatabaseSelect();
            }
            
            els.useHeroCover.checked = appState.config.use_hero_cover;
            els.useIconIcon.checked = appState.config.use_icon_icon;
        }
    } catch (err) {
        console.error("Failed to load config", err);
    }
}

async function saveApiKeys() {
    const notion = els.notionToken.value.trim();
    const sgdb = els.sgdbKey.value.trim();
    const steamKey = els.steamApiKey.value.trim();
    const steamId = els.steamId64.value.trim();
    const proxy = els.proxyUrl ? els.proxyUrl.value.trim() : '';
    
    try {
        const body = {};
        if (notion) body.notion_token = notion;
        if (sgdb) body.steamgriddb_key = sgdb;
        if (steamKey) body.steam_api_key = steamKey;
        if (steamId !== undefined) body.steam_id64 = steamId;
        if (els.proxyUrl) body.proxy = proxy;
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error('保存配置失败');
        showToast('密钥及代理配置已成功保存！', 'success');
        els.notionToken.value = '';
        els.sgdbKey.value = '';
        els.steamApiKey.value = '';
        await loadConfig();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function fetchDatabases() {
    try {
        els.fetchDbsBtn.disabled = true;
        els.fetchDbsBtn.textContent = '加载中...';
        
        const res = await fetch('/api/notion/databases');
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || '获取数据库列表失败，请检查网络代理或 Token');
        }
        const dbs = await res.json();
        
        els.dbSelect.innerHTML = '<option value="">-- 选择数据库 --</option>';
        dbs.forEach(db => {
            const opt = document.createElement('option');
            opt.value = db.id;
            opt.textContent = db.title;
            // Store properties on the option for easy access
            opt.dataset.props = JSON.stringify(db.properties);
            els.dbSelect.appendChild(opt);
        });
        els.dbSelect.disabled = false;
        showToast('数据库列表已更新', 'success');
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        els.fetchDbsBtn.disabled = false;
        els.fetchDbsBtn.textContent = '加载数据库列表';
    }
}

async function onDatabaseSelect() {
    const selected = els.dbSelect.options[els.dbSelect.selectedIndex];
    if (!selected.value) {
        els.mappingTableBody.innerHTML = '';
        return;
    }

    appState.config.database_id = selected.value;
    appState.notionProperties = JSON.parse(selected.dataset.props);
    renderMappingTable();
}

// 解析某个字段应当选中的 Notion 属性（严格以用户的选择为准，不做任何猜测）：
//   * 已映射（属性名非空）→ 原样采用，绝不按别名换列
//   * 该属性名不在本次拉取的库结构里 → 也原样保留（让用户看到真实选择，写入时报错也好过写错列）
//   * 未映射（属性名为空）→ 就是"不映射"，默认停在 -- 不映射 --，不再自动推荐
function resolveMappedProperty(allProps, mappedProp) {
    const names = Object.keys(allProps || {});
    const wanted = (mappedProp || '').trim();
    if (!wanted) {
        return '';
    }
    const exact = names.find(n => n === wanted) ||
                  names.find(n => n.trim().toLowerCase() === wanted.toLowerCase());
    return exact || wanted;
}

// 记录上一次渲染映射表所依据的数据；数据没变时不再重建表格。
// 目的：打开设置面板会异步拉取数据库列表并重渲染表格，若不加保护，
// 会把用户刚刚取消/勾选的改动直接覆盖回去（历史 bug：取消勾选后又被全部勾上）。
let lastMappingRenderKey = null;

function renderMappingTable() {
    const mapping = appState.config.field_mapping || {};
    const allProps = appState.notionProperties || {};
    const renderKey = JSON.stringify([appState.config.database_id || '', Object.keys(allProps).sort(), mapping]);
    if (renderKey === lastMappingRenderKey && els.mappingTableBody.children.length > 0) {
        return;   // 数据未变：保留当前表格（含用户尚未保存的勾选状态）
    }
    lastMappingRenderKey = renderKey;

    els.mappingTableBody.innerHTML = '';
    DEFAULT_FIELDS.forEach(field => {
        const tr = document.createElement('tr');
        
        // Enabled checkbox：配置里没有该字段时默认"未勾选"（尚未映射 → 不启用）
        const fieldConf = mapping[field.key];
        const isEnabled = fieldConf ? (fieldConf.enabled !== false) : false;
        const currentMapped = fieldConf ? (fieldConf.property || '') : '';

        // 用户已选定的属性原样保留；未映射则为 "-- 不映射 --"
        const mappedValue = resolveMappedProperty(allProps, currentMapped);

        // 下拉项 = 类型兼容的属性 + 用户已选定的属性
        // （即使其类型不在推荐范围内，也必须可见可选，否则用户的映射会被静默丢失）
        const optionNames = Object.keys(allProps).filter(n => field.type.includes(allProps[n].type));
        if (mappedValue && !optionNames.includes(mappedValue)) {
            optionNames.unshift(mappedValue);
        }

        let optionsHtml = '<option value="">-- 不映射 --</option>';
        optionNames.forEach(name => {
            const propInfo = allProps[name];
            const ptype = propInfo ? propInfo.type : '不在当前数据库';
            const warn = (propInfo && !field.type.includes(ptype)) ? ' ⚠️类型不推荐' : '';
            const sel = (name === mappedValue) ? 'selected' : '';
            optionsHtml += `<option value="${name}" ${sel}>${name} (${ptype}${warn})</option>`;
        });

        tr.innerHTML = `
            <td><input type="checkbox" class="map-enable" data-key="${field.key}" ${isEnabled ? 'checked' : ''}></td>
            <td>${field.label} (${field.key})</td>
            <td>
                <select class="map-select" data-key="${field.key}">
                    ${optionsHtml}
                </select>
            </td>
        `;
        els.mappingTableBody.appendChild(tr);
    });
}

async function saveConfig() {
    const frontendMapping = {};
    const backendMapping = {};
    const rawMapping = (appState.rawConfig && appState.rawConfig.field_mapping) || {};
    
    document.querySelectorAll('.mapping-table tbody tr').forEach(tr => {
        const key = tr.querySelector('.map-enable').dataset.key;
        const enabled = tr.querySelector('.map-enable').checked;
        const property = tr.querySelector('.map-select').value;
        
        frontendMapping[key] = { enabled, property };
        
        // Convert to backend format: record both enabled status and property
        const propInfo = appState.notionProperties ? appState.notionProperties[property] : null;
        const fallbackType = (rawMapping[key] && rawMapping[key].type) || 'rich_text';
        backendMapping[key] = { 
            name: property, 
            type: propInfo ? propInfo.type : fallbackType,
            enabled: enabled
        };
    });

    // Send backend-compatible config
    // 注意：若数据库列表未成功加载，dbSelect 只有空占位、映射表为空，
    // 此时绝不能把空值提交给后端，否则会清空已保存的数据库选择与字段映射。
    const backendConfig = {
        use_hero_as_cover: els.useHeroCover.checked,
        use_icon_as_page_icon: els.useIconIcon.checked
    };
    const selectedDbId = els.dbSelect.value;
    if (selectedDbId) backendConfig.database_id = selectedDbId;
    if (Object.keys(backendMapping).length > 0) backendConfig.field_mapping = backendMapping;

    const notionVal = els.notionToken.value.trim();
    const sgdbVal = els.sgdbKey.value.trim();
    const steamKeyVal = els.steamApiKey.value.trim();
    const steamIdVal = els.steamId64.value.trim();
    if (notionVal) backendConfig.notion_token = notionVal;
    if (sgdbVal) backendConfig.steamgriddb_key = sgdbVal;
    if (steamKeyVal) backendConfig.steam_api_key = steamKeyVal;
    if (steamIdVal !== undefined) backendConfig.steam_id64 = steamIdVal;

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(backendConfig)
        });
        if (!res.ok) throw new Error('Save failed');
        
        // Update local state（仅在本次确实提交了对应配置时同步，避免用空值覆盖本地状态）
        if (backendConfig.database_id) appState.config.database_id = backendConfig.database_id;
        appState.config.use_hero_cover = backendConfig.use_hero_as_cover;
        appState.config.use_icon_icon = backendConfig.use_icon_as_page_icon;
        if (Object.keys(frontendMapping).length > 0) appState.config.field_mapping = frontendMapping;
        
        if (notionVal || sgdbVal || steamKeyVal || steamIdVal) {
            els.notionToken.value = '';
            els.sgdbKey.value = '';
            els.steamApiKey.value = '';
            await loadConfig();
        }

        showToast('配置已保存', 'success');
        els.modal.classList.add('hidden');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// --- Submit ---

async function handleSubmit() {
    // 若查重仍在进行中，先等它结束：命中已存在条目时绝不能再新建，否则会产生重复页面
    if (pendingExistenceCheck) {
        try { await pendingExistenceCheck; } catch (e) { console.warn('Existence check failed:', e); }
    }
    if (appState.editMode) {
        showToast('检测到该游戏已存在于 Notion 中（已自动切换为编辑模式），请使用「🖼️ 仅更新图片」或「🔄 更新全部字段」。', 'info');
        return;
    }

    // Gather current form data (user might have edited it)
    const gameToSubmit = {
        title: els.title.value.trim(),
        title_en: els.titleEn.value.trim(),
        description: els.description.value.trim(),
        developers: els.developer.value.split(',').map(s => s.trim()).filter(Boolean),
        publishers: els.publisher.value.split(',').map(s => s.trim()).filter(Boolean),
        genres: appState.gameData ? (appState.gameData.genres || []) : [],
        tags: (appState.selectedTags && appState.selectedTags.size > 0)
            ? Array.from(appState.selectedTags)
            : ((appState.gameData && appState.gameData.tags) ? appState.gameData.tags.slice(0, 5) : []),
        release_date: els.releaseDate.value,
        release_date_iso: els.releaseDate.value,
        playtime: els.playtime && els.playtime.value.trim() !== '' ? parseFloat(els.playtime.value) : null,
        header_image: appState.gameData ? appState.gameData.header_image : '',
        steam_images: appState.gameData ? (appState.gameData.steam_images || {}) : {},
        steam_url: els.steamUrl.value
    };

    if (!gameToSubmit.title) {
        showToast('游戏名称不能为空', 'error');
        return;
    }

    const payload = {
        game: gameToSubmit,
        images: {
            grid: appState.selectedImages.grid || '',
            hero: appState.selectedImages.hero || '',
            icon: appState.selectedImages.icon || ''
        }
    };

    els.submitBtn.disabled = true;
    els.submitBtn.textContent = '提交中...';

    try {
        const res = await fetch('/api/notion/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data || data.status === 'error') {
            throw new Error((data && data.message) || '推送失败，请检查网络代理或稍后重试');
        }

        const notionLink = data.url ? `<a href="${data.url}" target="_blank" style="color: white; text-decoration: underline;">在 Notion 中查看</a>` : '已推送到 Notion 页面';
        if (data.reconciled) {
            showToast(`⚠️ 请求超时，但已核对确认该页面在 Notion 中创建成功：${notionLink}`, 'success');
        } else {
            showToast(`🎉 成功！${notionLink}`, 'success');
        }
        
        // Clear UI
        els.searchInput.value = '';
        els.gameInfoSection.classList.add('hidden');
        els.gallerySection.classList.add('hidden');
        els.submitSection.classList.add('hidden');
        
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        els.submitBtn.disabled = false;
        els.submitBtn.textContent = '📤 提交到 Notion';
    }
}

// --- Edit Mode & Notion Existence Check ---

async function checkNotionExistence(steamData) {
    if (!steamData) return;
    try {
        const res = await fetch('/api/notion/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: steamData.title || '',
                title_en: steamData.title_en || '',
                steam_url: steamData.steam_url || ''
            })
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data.found && data.page_id) {
            enterEditMode(data);
        } else {
            exitEditMode();
        }
    } catch (err) {
        console.warn('Check Notion existence error:', err);
        exitEditMode();
    }
}

function enterEditMode(searchResult) {
    appState.editMode = true;
    appState.existingPageId = searchResult.page_id;
    appState.existingPageUrl = searchResult.page_url;
    appState.notionGameProps = searchResult.properties || {};

    if (els.editBanner) els.editBanner.classList.remove('hidden');
    if (els.editBannerLink) {
        els.editBannerLink.href = searchResult.page_url || '#';
        els.editBannerLink.style.display = searchResult.page_url ? 'inline-block' : 'none';
    }
    if (els.btnResetToSteam) els.btnResetToSteam.classList.remove('hidden');
    if (els.createBtnGroup) els.createBtnGroup.classList.add('hidden');
    if (els.editBtnGroup) els.editBtnGroup.classList.remove('hidden');

    // 用 Notion 现有数据填充表单
    populateFormFromNotion(searchResult.properties || {});
    showToast('⚠️ 检测到该游戏已存在于 Notion 数据库中，已自动切换为编辑模式', 'info');
}

function exitEditMode() {
    appState.editMode = false;
    appState.existingPageId = null;
    appState.existingPageUrl = null;
    appState.notionGameProps = null;

    if (els.editBanner) els.editBanner.classList.add('hidden');
    if (els.btnResetToSteam) els.btnResetToSteam.classList.add('hidden');
    if (els.createBtnGroup) els.createBtnGroup.classList.remove('hidden');
    if (els.editBtnGroup) els.editBtnGroup.classList.add('hidden');
}

function populateFormFromNotion(props) {
    if (!props) return;
    // 只读取"映射到该字段的 Notion 属性"的值：绝不按 "标签"/"类型" 等固定名字去猜别的列
    // （后端已按映射把属性名翻译成 tags/genre 等 key，读不到就说明该字段未映射）
    const getVal = (key) => {
        if (props[key] !== undefined && props[key] !== null) return props[key];
        return null;
    };

    const titleVal = getVal('title');
    if (titleVal !== null) els.title.value = titleVal;

    const titleEnVal = getVal('title_en');
    if (titleEnVal !== null) els.titleEn.value = titleEnVal;

    const devVal = getVal('developer');
    if (devVal !== null) els.developer.value = Array.isArray(devVal) ? devVal.join(', ') : devVal;

    const pubVal = getVal('publisher');
    if (pubVal !== null) els.publisher.value = Array.isArray(pubVal) ? pubVal.join(', ') : pubVal;

    const dateVal = getVal('release_date');
    if (dateVal !== null) els.releaseDate.value = dateVal;

    const playVal = getVal('playtime');
    if (playVal !== null && els.playtime) {
        if (typeof playVal === 'number') {
            els.playtime.value = playVal;
        } else {
            const m = String(playVal).match(/[\d.]+/);
            els.playtime.value = m ? parseFloat(m[0]) : '';
        }
    }

    const descVal = getVal('description');
    if (descVal !== null) els.description.value = descVal;

    const urlVal = getVal('steam_url');
    if (urlVal !== null) els.steamUrl.value = urlVal;

    // Genres 回填
    const genresVal = getVal('genre');
    if (genresVal && appState.gameData) {
        const notionGenres = Array.isArray(genresVal) ? genresVal : [genresVal];
        appState.gameData.genres = notionGenres.filter(Boolean);
        renderGenres();
    }

    // Tags 回填与高亮
    const tagsVal = getVal('tags');
    if (tagsVal && appState.gameData) {
        const rawNotionTags = Array.isArray(tagsVal) ? tagsVal : [tagsVal];
        const notionTags = rawNotionTags.map(decodeUnicodeString).filter(Boolean);
        if (!appState.gameData.tags) appState.gameData.tags = [];
        if (notionTags.length > 0) {
            notionTags.forEach(t => {
                if (t && !appState.gameData.tags.includes(t)) {
                    appState.gameData.tags.unshift(t);
                }
            });
            appState.selectedTags = new Set(notionTags);
        } else {
            // 若 Notion 当前条目无标签，保留已选或回退为 Steam 前 5 个标签，绝不清空
            if (!appState.selectedTags || appState.selectedTags.size === 0) {
                appState.selectedTags = new Set((appState.gameData.tags || []).slice(0, 5));
            }
        }
        renderTags();
    }
}

async function handleUpdate(onlyImages) {
    if (!appState.existingPageId) {
        showToast('未找到已有 Notion 页面 ID', 'error');
        return;
    }

    if (onlyImages) {
        if (!appState.selectedImages.grid && !appState.selectedImages.hero && !appState.selectedImages.icon) {
            showToast('请至少在画廊中选择一张图片（封面、横幅或图标）', 'warning');
            return;
        }
    }

    const gameToSubmit = {
        title: els.title.value.trim(),
        title_en: els.titleEn.value.trim(),
        description: els.description.value.trim(),
        developers: els.developer.value.split(',').map(s => s.trim()).filter(Boolean),
        publishers: els.publisher.value.split(',').map(s => s.trim()).filter(Boolean),
        genres: appState.gameData ? (appState.gameData.genres || []) : [],
        tags: (appState.selectedTags && appState.selectedTags.size > 0)
            ? Array.from(appState.selectedTags)
            : ((appState.gameData && appState.gameData.tags) ? appState.gameData.tags.slice(0, 5) : []),
        release_date: els.releaseDate.value,
        release_date_iso: els.releaseDate.value,
        playtime: els.playtime && els.playtime.value.trim() !== '' ? parseFloat(els.playtime.value) : null,
        header_image: appState.gameData ? appState.gameData.header_image : '',
        steam_images: appState.gameData ? (appState.gameData.steam_images || {}) : {},
        steam_url: els.steamUrl.value
    };

    if (!onlyImages && !gameToSubmit.title) {
        showToast('游戏名称不能为空', 'error');
        return;
    }

    const payload = {
        page_id: appState.existingPageId,
        only_images: onlyImages,
        game: gameToSubmit,
        images: {
            grid: appState.selectedImages.grid || '',
            hero: appState.selectedImages.hero || '',
            icon: appState.selectedImages.icon || ''
        }
    };

    const targetBtn = onlyImages ? els.updateImagesBtn : els.updateAllBtn;
    const oldText = targetBtn.textContent;
    targetBtn.disabled = true;
    targetBtn.textContent = '更新中...';

    try {
        const res = await fetch('/api/notion/update', {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data || data.status === 'error') {
            throw new Error((data && data.message) || '更新失败，请检查网络或稍后重试');
        }

        const notionUrl = data.url || appState.existingPageUrl;
        const linkHtml = notionUrl ? `<a href="${notionUrl}" target="_blank" style="color: white; text-decoration: underline;">在 Notion 中查看</a>` : 'Notion 页面已更新';
        showToast(`🎉 更新成功！${linkHtml}`, 'success');

        // Clear UI
        els.searchInput.value = '';
        els.gameInfoSection.classList.add('hidden');
        els.gallerySection.classList.add('hidden');
        els.submitSection.classList.add('hidden');
        exitEditMode();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        targetBtn.disabled = false;
        targetBtn.textContent = oldText;
    }
}
