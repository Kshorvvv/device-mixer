package io.github.kshorvvv.devicemixer;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

public class MainActivity extends Activity {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newFixedThreadPool(2);
    private final AtomicBoolean polling = new AtomicBoolean();
    private SharedPreferences prefs;
    private TextView modeLabel, detail, devices;
    private Button toggle;
    private EditText pairing;
    private volatile String host = "", fingerprint = "", token = "";
    private volatile int port;
    private boolean active, recovery, foreground;
    private NsdManager nsd;
    private NsdManager.DiscoveryListener discovery;
    private final Runnable refresh = new Runnable() {
        @Override public void run() { if (foreground) { poll(); ui.postDelayed(this, 2500); } }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("connection", MODE_PRIVATE);
        host = prefs.getString("host", ""); port = prefs.getInt("port", 0); fingerprint = prefs.getString("fingerprint", "");
        try { token = decrypt(prefs.getString("token", "")); } catch (Exception ignored) { token = ""; }
        build(); acceptIntent(getIntent()); discover();
    }
    @Override public void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); acceptIntent(intent); }
    @Override public void onResume() { super.onResume(); foreground = true; ui.removeCallbacks(refresh); ui.post(refresh); }
    @Override public void onPause() { foreground = false; ui.removeCallbacks(refresh); super.onPause(); }
    @Override public void onDestroy() {
        if (nsd != null && discovery != null) try { nsd.stopServiceDiscovery(discovery); } catch (Exception ignored) {}
        network.shutdownNow(); super.onDestroy();
    }
    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color) {
        TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setPadding(0, dp(6), 0, dp(6)); return t;
    }
    private GradientDrawable card(int color, int radius) { GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d; }
    private void build() {
        getWindow().setStatusBarColor(Color.rgb(244, 248, 251)); getWindow().setNavigationBarColor(Color.rgb(244, 248, 251));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        ScrollView scroll = new ScrollView(this); scroll.setBackgroundColor(Color.rgb(244, 248, 251));
        LinearLayout body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL); body.setPadding(dp(24), dp(42), dp(24), dp(30)); scroll.addView(body);
        TextView title = text("设备混音", 30, Color.rgb(20, 40, 55)); title.setTypeface(null, Typeface.BOLD); body.addView(title);
        body.addView(text("手机控制 · Mac 汇合声音", 16, Color.rgb(90, 108, 122)));
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(dp(20), dp(18), dp(20), dp(18)); panel.setBackground(card(Color.WHITE, 20));
        LinearLayout.LayoutParams panelParams = new LinearLayout.LayoutParams(-1, -2); panelParams.setMargins(0, dp(24), 0, dp(20)); body.addView(panel, panelParams);
        modeLabel = text("正在连接 Mac…", 24, Color.rgb(13, 148, 136)); modeLabel.setTypeface(null, Typeface.BOLD); panel.addView(modeLabel);
        detail = text("配对后即可在这里开启和恢复普通使用。", 15, Color.rgb(90, 108, 122)); panel.addView(detail);
        devices = text("", 14, Color.rgb(90, 108, 122)); panel.addView(devices);
        toggle = new Button(this); toggle.setText("开启混音"); toggle.setTextSize(19); toggle.setAllCaps(false); toggle.setTextColor(Color.WHITE); toggle.setBackground(card(Color.rgb(13, 148, 136), 16));
        body.addView(toggle, new LinearLayout.LayoutParams(-1, dp(60))); toggle.setOnClickListener(v -> command(active || recovery ? "stop" : "start"));
        Button retry = new Button(this); retry.setText("刷新连接 / 设备"); retry.setAllCaps(false); body.addView(retry); retry.setOnClickListener(v -> { discover(); command("refresh"); poll(); });
        body.addView(text("普通模式不转发声音，耳机照常使用。只有点开启时才进入混音；Mac 需保持开机，两端处于同一可互通网络。", 14, Color.rgb(90, 108, 122)));
        body.addView(text("首次配对", 18, Color.rgb(20, 40, 55)));
        pairing = new EditText(this); pairing.setHint("粘贴 Mac 的配对链接"); pairing.setSingleLine(true); pairing.setTextSize(13); body.addView(pairing);
        Button pair = new Button(this); pair.setText("连接这台 Mac"); pair.setAllCaps(false); body.addView(pair); pair.setOnClickListener(v -> pair(pairing.getText().toString().trim()));
        body.addView(text("也可在 Mac 点击“安装并配对手机端”，自动完成。此应用只申请联网权限，不申请麦克风或相机，不保存录音。", 13, Color.rgb(110, 125, 135)));
        setContentView(scroll);
    }
    private void acceptIntent(Intent intent) {
        String value = intent.getStringExtra("pair_uri");
        if (value == null && intent.getData() != null) value = intent.getData().toString();
        if (value != null && value.startsWith("devicemixer://pair?")) { pair(value); intent.removeExtra("pair_uri"); intent.setData(null); }
    }
    private static String hex(byte[] bytes) { StringBuilder s = new StringBuilder(); for (byte b : bytes) s.append(String.format(Locale.ROOT, "%02x", b & 255)); return s.toString(); }
    private JSONObject request(String server, int serverPort, String pin, String credential, String path, JSONObject body) throws Exception {
        if (pin.length() != 64 || serverPort < 1 || serverPort > 65535) throw new Exception("尚未配对");
        TrustManager[] trust = { new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] c, String a) throws CertificateException { throw new CertificateException("server only"); }
            public void checkServerTrusted(X509Certificate[] c, String a) throws CertificateException {
                try {
                    if (c.length == 0 || !MessageDigest.isEqual(hex(MessageDigest.getInstance("SHA-256").digest(c[0].getEncoded())).getBytes(StandardCharsets.US_ASCII), pin.getBytes(StandardCharsets.US_ASCII))) throw new CertificateException("Mac 身份不匹配");
                    c[0].checkValidity();
                } catch (CertificateException e) { throw e; } catch (Exception e) { throw new CertificateException(e); }
            }
        }};
        SSLContext tls = SSLContext.getInstance("TLS"); tls.init(null, trust, null);
        HttpsURLConnection connection = (HttpsURLConnection) new URL("https", server, serverPort, path).openConnection();
        connection.setSSLSocketFactory(tls.getSocketFactory());
        // The exact paired certificate is verified above; the Mac's LAN IP may change.
        connection.setHostnameVerifier((hostname, session) -> true);
        connection.setConnectTimeout(5000); connection.setReadTimeout(5000);
        if (!credential.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + credential);
        try {
            if (body != null) { connection.setRequestMethod("POST"); connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json"); connection.getOutputStream().write(body.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode();
            if (code < 200 || code >= 300) throw new Exception(code == 401 ? "请重新配对 Mac" : "操作未完成（" + code + "）");
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[2048]; int n; while ((n = input.read(buffer)) != -1) { out.write(buffer, 0, n); if (out.size() > 32768) throw new Exception("响应过大"); }
                return new JSONObject(out.toString("UTF-8"));
            }
        } finally { connection.disconnect(); }
    }
    private void pair(String value) {
        try {
            Uri uri = Uri.parse(value); final String h = uri.getQueryParameter("h"), fp = uri.getQueryParameter("f"), key = uri.getQueryParameter("k"); final int p = Integer.parseInt(uri.getQueryParameter("p"));
            if (!"devicemixer".equals(uri.getScheme()) || h == null || fp == null || key == null) throw new Exception();
            detail.setText("正在核对 Mac 身份并配对…");
            network.execute(() -> {
                try {
                    JSONObject body = new JSONObject(); body.put("key", key); JSONObject result = request(h, p, fp, "", "/pair", body);
                    String newToken = result.getString("token");
                    prefs.edit().putString("host", h).putInt("port", p).putString("fingerprint", fp).putString("token", encrypt(newToken)).apply();
                    host = h; port = p; fingerprint = fp; token = newToken;
                    ui.post(() -> { pairing.setText(""); detail.setText("已与 Mac 安全配对。"); discover(); poll(); });
                } catch (Exception e) { ui.post(() -> detail.setText("配对未完成：" + e.getMessage())); }
            });
        } catch (Exception e) { detail.setText("请使用 Mac 显示的完整配对链接。"); }
    }
    private void poll() {
        if (token.isEmpty() || !polling.compareAndSet(false, true)) return;
        network.execute(() -> {
            try {
                JSONObject state = request(host, port, fingerprint, token, "/status", null);
                ui.post(() -> {
                    String mode = state.optString("mode", "normal"); active = mode.equals("mixing") || mode.equals("connecting"); recovery = mode.equals("recovery");
                    modeLabel.setText(mode.equals("mixing") ? "混音中" : mode.equals("connecting") ? "正在连接…" : mode.equals("recovery") ? "设置待恢复" : "普通模式");
                    detail.setText(state.optString("message", "")); toggle.setText(active || recovery ? "恢复普通使用" : "开启混音");
                    devices.setText("耳机：" + state.optString("headphone", "") + "\n已启用安卓设备：" + state.optInt("device_count", 0));
                });
            } catch (Exception e) { ui.post(() -> { modeLabel.setText("Mac 暂未连接"); detail.setText("请确认 Mac 客户端已打开，手机与 Mac 网络可互通。可刷新连接或重新配对。"); }); }
            finally { polling.set(false); }
        });
    }
    private void command(String action) {
        if (token.isEmpty()) { detail.setText("请先从 Mac 安装并配对，或粘贴配对链接。"); return; }
        network.execute(() -> {
            try { JSONObject body = new JSONObject(); body.put("action", action); request(host, port, fingerprint, token, "/command", body); ui.post(() -> { detail.setText("指令已发送，正在等待 Mac 更新…"); ui.postDelayed(this::poll, 500); }); }
            catch (Exception e) { ui.post(() -> detail.setText("未能连接 Mac，请刷新后重试。")); }
        });
    }
    private void discover() {
        if (nsd == null) nsd = (NsdManager)getSystemService(NSD_SERVICE);
        if (discovery != null) try { nsd.stopServiceDiscovery(discovery); } catch (Exception ignored) {}
        discovery = new NsdManager.DiscoveryListener() {
            public void onDiscoveryStarted(String t) {}
            public void onDiscoveryStopped(String t) {}
            public void onStartDiscoveryFailed(String t,int e) {}
            public void onStopDiscoveryFailed(String t,int e) {}
            public void onServiceLost(NsdServiceInfo s) {}
            public void onServiceFound(NsdServiceInfo s) {
                if (!s.getServiceType().contains("_devicemix._tcp")) return;
                nsd.resolveService(s, new NsdManager.ResolveListener() {
                    public void onResolveFailed(NsdServiceInfo i,int e) {}
                    public void onServiceResolved(NsdServiceInfo i) {
                        byte[] fp = i.getAttributes().get("fp");
                        if (fp != null && !fingerprint.isEmpty() && fingerprint.equals(new String(fp,StandardCharsets.US_ASCII))) {
                            host = i.getHost().getHostAddress(); port = i.getPort();
                            prefs.edit().putString("host",host).putInt("port",port).apply(); ui.post(MainActivity.this::poll);
                        }
                    }
                });
            }
        };
        try { nsd.discoverServices("_devicemix._tcp.", NsdManager.PROTOCOL_DNS_SD, discovery); } catch (Exception ignored) {}
    }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias("device_mixer_remote")) return (SecretKey)store.getKey("device_mixer_remote", null);
        KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        g.init(new KeyGenParameterSpec.Builder("device_mixer_remote",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build()); return g.generateKey();
    }
    private String encrypt(String value) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.ENCRYPT_MODE,key()); byte[] encrypted = c.doFinal(value.getBytes(StandardCharsets.UTF_8)); byte[] result = new byte[c.getIV().length+encrypted.length]; System.arraycopy(c.getIV(),0,result,0,c.getIV().length); System.arraycopy(encrypted,0,result,c.getIV().length,encrypted.length); return Base64.encodeToString(result,Base64.NO_WRAP);
    }
    private String decrypt(String value) throws Exception {
        if (value.isEmpty()) return ""; byte[] data = Base64.decode(value,Base64.NO_WRAP); Cipher c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,data,0,12)); return new String(c.doFinal(data,12,data.length-12),StandardCharsets.UTF_8);
    }
}
