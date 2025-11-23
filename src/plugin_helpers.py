# plugin_scanner.py

import os
import time
import threading
from typing import List, Dict, Optional
from pedalboard import load_plugin  # Pedalboard can load VST3/AU
# Note: this only verifies plugin files load-able, not full metadata extraction
# You might need to inspect plugin metadata separately if required.

class PluginScanner:
    """
    Scans standard plugin folders using Pedalboard, caches the list,
    and provides lookup for plugin names/paths for use by the MCP server.
    """
    def __init__(self,
                 plugin_paths: Optional[List[str]] = None,
                 cache_ttl_seconds: int = 300,
                 validate_plugins: bool = False):
        """
        :param plugin_paths: list of folders to scan (if None, uses default folders per OS)
        :param cache_ttl_seconds: time to keep cache valid before auto-rescan
        :param validate_plugins: if True, attempt to load each plugin via Pedalboard (slower)
        """
        if plugin_paths is None:
            plugin_paths = self._default_paths()
        self.plugin_paths = plugin_paths
        self.cache_ttl_seconds = cache_ttl_seconds
        self.validate_plugins = validate_plugins
        self._cache_timestamp: float = 0.0
        self._cache: List[Dict[str, str]] = []  # each dict: { "name": str, "path": str }
        self._lock = threading.Lock()

    def _default_paths(self) -> List[str]:
        # Define common plugin install paths for macOS/Windows/Linux
        paths = []
        if os.name == 'posix':
            # Likely macOS or Linux
            # macOS typical:
            paths += [
                '/Library/Audio/Plug-Ins/VST3',
                '/Library/Audio/Plug-Ins/VST',
                '/Library/Audio/Plug-Ins/Components',  # AU
                os.path.expanduser('~/Library/Audio/Plug-Ins/VST3'),
                os.path.expanduser('~/Library/Audio/Plug-Ins/VST'),
                os.path.expanduser('~/Library/Audio/Plug-Ins/Components'),
            ]
        elif os.name == 'nt':
            # Windows typical
            paths += [
                'C:\\Program Files\\VSTPlugins',
                'C:\\Program Files\\Steinberg\\VSTPlugins',
                'C:\\Program Files\\Common Files\\VST3',
            ]
        # Filter to those that exist
        real_paths = [p for p in paths if os.path.isdir(p)]
        return real_paths

    def _scan_folder(self, folder: str) -> List[Dict[str, str]]:
        """
        Scan one folder for plugin files, try loading via Pedalboard to validate,
        then return list of {'name':.., 'path': ..}
        """
        print(f"[plugin_scan] scanning {folder}")
        results = []
        for root, dirs, files in os.walk(folder):
            # Log plugin subdirectories encountered to aid troubleshooting
            plugin_dirs = [d for d in dirs if d and not d.startswith(".")]
            if plugin_dirs:
                print(f"[plugin_scan] dirs in {root}: {', '.join(plugin_dirs)}")

            # Attempt to load bundle-style plugins before descending (macOS .vst3/.component)
            for d in list(dirs):
                if d.lower().endswith(('.vst3', '.component', '.vst')):
                    full = os.path.join(root, d)
                    if self.validate_plugins:
                        try:
                            plugin = load_plugin(full)
                            name = plugin.plugin_name if hasattr(plugin, 'plugin_name') else d
                            results.append({"name": name, "path": full})
                        except Exception:
                            # skip invalid/broken plugins
                            pass
                    else:
                        # Fast path: record without loading
                        results.append({"name": d, "path": full})
                    # prevent duplicate scans by not descending into the bundle
                    dirs.remove(d)

            for fn in files:
                # filter common plugin file extensions
                if fn.lower().endswith(('.vst3', '.vst', '.component', '.au', '.so', '.dylib')):
                    full = os.path.join(root, fn)
                    if self.validate_plugins:
                        try:
                            # Attempt to load plugin to check it's valid
                            plugin = load_plugin(full)
                            name = plugin.plugin_name if hasattr(plugin, 'plugin_name') else fn
                            results.append({"name": name, "path": full})
                        except Exception:
                            # skip invalid/broken plugins
                            continue
                    else:
                        results.append({"name": fn, "path": full})
        return results

    def _rescan(self):
        """Perform a full scan of plugin_paths and populate cache."""
        combined = []
        for p in self.plugin_paths:
            try:
                scanned = self._scan_folder(p)
                combined.extend(scanned)
            except Exception:
                continue
        with self._lock:
            self._cache = combined
            self._cache_timestamp = time.time()

    def ensure_cache(self):
        """Ensure cache is fresh: if stale, trigger rescan."""
        now = time.time()
        if (now - self._cache_timestamp) > self.cache_ttl_seconds or not self._cache:
            # Rescan outside blocking path
            self._rescan()

    def get_installed_plugins(self) -> List[Dict[str, str]]:
        """
        Return the cached list of plugin dictionaries.
        Each dict has keys: 'name', 'path'
        """
        self.ensure_cache()
        with self._lock:
            return list(self._cache)

    def force_scan(self):
        """Force a fresh scan regardless of TTL."""
        self._rescan()
        with self._lock:
            return list(self._cache)
