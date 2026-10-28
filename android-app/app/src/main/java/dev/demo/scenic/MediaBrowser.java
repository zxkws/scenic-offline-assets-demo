package dev.demo.scenic;

import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.media.MediaPlayer;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.MediaController;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.VideoView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;

/**
 * Render any category and any number of items. There is deliberately no
 * switch on category codes such as guide_audio or background_music.
 * File mimeType decides which simple media viewer can be used.
 */
final class MediaBrowser {
    private final Activity activity;
    private final LinearLayout root;
    private MediaPlayer audio;
    private VideoView video;

    MediaBrowser(Activity activity, LinearLayout root) {
        this.activity = activity;
        this.root = root;
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    void clear() {
        stopMedia();
        root.removeAllViews();
    }

    void label(String text, int sp, int color) {
        TextView label = new TextView(activity);
        label.setText(text);
        label.setTextSize(sp);
        label.setTextColor(color);
        label.setPadding(dp(4), dp(10), dp(4), dp(4));
        root.addView(label);
    }

    void showScenic(JSONObject manifest, File scenicFolder) throws Exception {
        label(manifest.getString("scenicName") + " · v" + manifest.getInt("version"), 23, Color.rgb(30, 58, 92));
        JSONObject files = manifest.getJSONObject("files");
        JSONArray stations = manifest.getJSONArray("stations");
        for (int stationIndex = 0; stationIndex < stations.length(); stationIndex++) {
            JSONObject station = stations.getJSONObject(stationIndex);
            label("站点：" + station.getString("name"), 19, Color.DKGRAY);
            JSONArray categories = station.getJSONArray("categories");
            for (int groupIndex = 0; groupIndex < categories.length(); groupIndex++) {
                JSONObject group = categories.getJSONObject(groupIndex);
                label("  " + group.getString("name") + " (" + group.optString("mediaType", "其他") + ")",
                      16, Color.rgb(75, 85, 99));
                JSONArray items = group.getJSONArray("items");
                for (int itemIndex = 0; itemIndex < items.length(); itemIndex++) {
                    JSONObject item = items.getJSONObject(itemIndex);
                    JSONObject metadata = files.getJSONObject(item.getString("fileId"));
                    String url = metadata.getString("url");
                    String hash = metadata.getString("sha256");
                    File local = new File(new File(scenicFolder, "files"),
                                          hash + url.substring(url.lastIndexOf('.')));
                    showItem(item.getString("title"), metadata.getString("mimeType"), local);
                }
            }
        }
    }

    private void showItem(String title, String mime, File file) {
        label("    " + title, 15, Color.BLACK);
        if (!file.isFile()) {
            label("    未下载", 12, Color.RED);
            return;
        }
        if (mime.startsWith("image/")) {
            // Bound the decoded image size, even if the original photo is enormous.
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inJustDecodeBounds = true;
            BitmapFactory.decodeFile(file.getAbsolutePath(), options);
            options.inSampleSize = 1;
            while (options.outWidth / options.inSampleSize > 900 ||
                   options.outHeight / options.inSampleSize > 600) {
                options.inSampleSize *= 2;
            }
            options.inJustDecodeBounds = false;
            Bitmap bitmap = BitmapFactory.decodeFile(file.getAbsolutePath(), options);
            if (bitmap == null) {
                label("    图片无法解码", 12, Color.RED);
                return;
            }
            ImageView image = new ImageView(activity);
            image.setImageBitmap(bitmap);
            image.setAdjustViewBounds(true);
            image.setScaleType(ImageView.ScaleType.FIT_CENTER);
            image.setMaxHeight(dp(160));
            root.addView(image, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(160)));
        } else if (mime.startsWith("audio/")) {
            Button play = new Button(activity);
            play.setText("播放音频 · " + title);
            root.addView(play);
            play.setOnClickListener(view -> {
                stopMedia();
                try {
                    audio = new MediaPlayer();
                    audio.setDataSource(file.getAbsolutePath());
                    audio.setOnCompletionListener(player -> {
                        player.release();
                        if (audio == player) audio = null;
                    });
                    audio.prepare();
                    audio.start();
                } catch (Exception e) {
                    stopMedia();
                    Toast.makeText(activity, "无法播放该音频", Toast.LENGTH_SHORT).show();
                }
            });
        } else if (mime.startsWith("video/")) {
            Button play = new Button(activity);
            play.setText("播放视频 · " + title);
            root.addView(play);
            VideoView player = new VideoView(activity);
            player.setVisibility(View.GONE);
            root.addView(player, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(240)));
            play.setOnClickListener(view -> {
                stopMedia();
                video = player;
                player.setVisibility(View.VISIBLE);
                MediaController controls = new MediaController(activity);
                player.setMediaController(controls);
                controls.setAnchorView(player);
                player.setVideoPath(file.getAbsolutePath());
                player.setOnErrorListener((media, what, extra) -> {
                    Toast.makeText(activity, "无法播放该视频", Toast.LENGTH_SHORT).show();
                    return true;
                });
                player.start();
            });
        } else {
            label("    不支持预览：" + mime, 12, Color.GRAY);
        }
    }

    void stopMedia() {
        if (audio != null) {
            audio.release();
            audio = null;
        }
        if (video != null) {
            video.stopPlayback();
            video.setVisibility(View.GONE);
            video = null;
        }
    }

    boolean isPlaying() {
        return (audio != null && audio.isPlaying()) ||
               (video != null && video.isPlaying());
    }
}
