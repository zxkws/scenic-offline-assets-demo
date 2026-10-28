package dev.demo.scenic;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Iterator;

/** Teaching demo: one background thread, hash-verified files and offline manifests. */
public class MainActivity extends Activity {
    // Android emulator host address. Replace with the LAN server for an actual vehicle.
    private static final String BASE = "http://10.0.2.2:8765";
    private static final String[] SCENICS = {"A", "B", "C"};
    private MediaBrowser browser;
    private TextView statusView;
    private Button[] scenicButtons;
    private String selectedScenic;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        selectedScenic = getPreferences(MODE_PRIVATE).getString("selectedScenic", "A");
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        statusView = new TextView(this);
        statusView.setTextSize(16);
        statusView.setPadding(24, 18, 24, 8);
        page.addView(statusView);
        LinearLayout tabs = new LinearLayout(this);
        tabs.setOrientation(LinearLayout.HORIZONTAL);
        scenicButtons = new Button[SCENICS.length];
        for (int i = 0; i < SCENICS.length; i++) {
            final String id = SCENICS[i];
            Button button = new Button(this);
            button.setText(id);
            button.setAllCaps(false);
            button.setOnClickListener(view -> {
                selectedScenic = id;
                getPreferences(MODE_PRIVATE).edit().putString("selectedScenic", id).apply();
                showSelected();
            });
            scenicButtons[i] = button;
            tabs.addView(button, new LinearLayout.LayoutParams(
                    0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        }
        page.addView(tabs);
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(24, 32, 24, 32);
        scroll.addView(content);
        page.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        browser = new MediaBrowser(this, content);
        setContentView(page);
        showSelected();
        setStatus("正在检查并同步三个景区…");
        new Thread(() -> {
            try { sync(); setStatus("三个景区同步完成，已下载素材可离线使用"); }
            catch (Exception e) {
                setStatus("同步失败，已有离线素材仍可使用：" + e.getMessage());
            }
        }, "scenic-sync").start();
    }

    private void setStatus(String status) {
        runOnUiThread(() -> {
            if (isDestroyed()) return;
            statusView.setText(status);
        });
    }

    private void showSelected() {
        // All three scenic areas are downloaded; only the selected one is displayed.
        // A change of selection is intentional and may stop current playback.
        browser.clear();
        for (int i = 0; i < SCENICS.length; i++) {
            File manifestFile = new File(getFilesDir(),
                    "scenic/" + SCENICS[i] + "/active.json");
            String name = "景区 " + SCENICS[i];
            if (manifestFile.isFile()) {
                try {
                    name = new JSONObject(read(manifestFile)).optString("scenicName", name);
                } catch (Exception ignored) {
                    // An invalid manifest will be reported for the selected scenic.
                }
            }
            scenicButtons[i].setText(name);
            scenicButtons[i].setAlpha(SCENICS[i].equals(selectedScenic) ? 1.0f : 0.65f);
        }
        File folder = new File(getFilesDir(), "scenic/" + selectedScenic);
        File active = new File(folder, "active.json");
        if (!active.isFile()) {
            browser.label("当前景区尚未完成下载，联网后会自动同步。", 16, Color.GRAY);
            return;
        }
        try {
            browser.showScenic(new JSONObject(read(active)), folder);
        } catch (Exception e) {
            browser.label("当前景区本地清单读取失败", 16, Color.RED);
        }
    }

    private void sync() throws Exception {
        JSONArray scenics = new JSONArray(fetch(BASE + "/api/scenics"));
        for (int i = 0; i < scenics.length(); i++) {
            String id = scenics.getJSONObject(i).getString("id");
            JSONObject manifest = new JSONObject(fetch(BASE + "/api/scenics/" + id + "/manifest"));
            File scenic = new File(getFilesDir(), "scenic/" + id);
            File files = new File(scenic, "files");
            if (!files.exists() && !files.mkdirs()) throw new IOException("mkdir failed");
            JSONObject all = manifest.getJSONObject("files");
            Iterator<String> keys = all.keys();
            while (keys.hasNext()) {
                JSONObject asset = all.getJSONObject(keys.next());
                String hash = asset.getString("sha256");
                String remote = asset.getString("url");
                File local = new File(files, hash + remote.substring(remote.lastIndexOf('.')));
                if (valid(local, asset)) continue;
                File part = new File(files, local.getName() + ".part");
                // A complete but corrupted .part cannot be resumed with HTTP Range.
                if (part.isFile() && part.length() >= asset.getLong("size") && !valid(part, asset)) {
                    if (!part.delete()) throw new IOException("remove corrupted partial file failed");
                }
                download(BASE + remote, part);
                if (!valid(part, asset)) throw new IOException("SHA-256 mismatch");
                if (!part.renameTo(local)) throw new IOException("rename failed");
            }
            File tmp = new File(scenic, "active.json.tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(manifest.toString().getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            if (!tmp.renameTo(new File(scenic, "active.json"))) throw new IOException("activate failed");
            runOnUiThread(() -> {
                if (isDestroyed()) return;
                statusView.setText("已同步景区 " + id + "，继续检查其他景区…");
                // Do not stop a playing audio/video merely because syncing finishes.
                if (id.equals(selectedScenic) && !browser.isPlaying()) showSelected();
            });
        }
    }

    private static String fetch(String url) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(30000);
        try (InputStream in = conn.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            copy(in, out);
            return out.toString("UTF-8");
        } finally { conn.disconnect(); }
    }

    private static String read(File file) throws IOException {
        try (InputStream in = new FileInputStream(file); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            copy(in, out);
            return out.toString("UTF-8");
        }
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[65536];
        int size;
        while ((size = in.read(buf)) != -1) out.write(buf, 0, size);
    }

    private static void download(String url, File part) throws IOException {
        long offset = part.isFile() ? part.length() : 0;
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(30000);
        if (offset > 0) conn.setRequestProperty("Range", "bytes=" + offset + "-");
        try {
            int status = conn.getResponseCode();
            String range = conn.getHeaderField("Content-Range");
            boolean resume = offset > 0 && status == 206 && range != null &&
                             range.startsWith("bytes " + offset + "-");
            if (status != 200 && !resume) throw new IOException("HTTP " + status);
            try (InputStream in = conn.getInputStream(); FileOutputStream out = new FileOutputStream(part, resume)) {
                copy(in, out);
                out.getFD().sync();
            }
        } finally { conn.disconnect(); }
    }

    private static boolean valid(File file, JSONObject meta) throws Exception {
        if (!file.isFile() || file.length() != meta.getLong("size")) return false;
        MessageDigest sha = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] buf = new byte[65536]; int n;
            while ((n = in.read(buf)) != -1) sha.update(buf, 0, n);
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : sha.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return meta.getString("sha256").equals(hex.toString());
    }

    @Override protected void onDestroy() {
        if (browser != null) browser.stopMedia();
        super.onDestroy();
    }
}
