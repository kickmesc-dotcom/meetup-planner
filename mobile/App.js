import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  BackHandler,
  Linking,
  Platform,
  Pressable,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Constants from "expo-constants";
import { WebView } from "react-native-webview";

/**
 * Standalone-оболочка для SemiWorkBot.
 *
 * Почему WebView, а не второй нативный клиент. Продукт — одно и то же
 * приложение для Telegram, браузера и телефона. Дублировать экраны на
 * React Native значило бы держать две правды о правах, задачах и онбординге.
 * Здесь нативная часть отвечает только за то, чего нет в вебе: запуск с
 * домашнего экрана, аппаратную кнопку «назад» и открытие внешних ссылок в
 * системном браузере.
 *
 * Что важно для входа: `domStorageEnabled` обязателен. Сессия хранится в
 * localStorage, и без него WebView терял бы вход между экранами.
 *
 * Адрес приложения можно переопределить без правки кода:
 * `EXPO_PUBLIC_APP_URL=https://… npm start`. Так тестируется локальная сборка
 * и будущий домен в зоне .ru.
 */
// Боевой адрес мини-аппа: именно этот origin есть в CORS бэкенда. Второй
// проект (`meetup-planner1.pages.dev`) — чужая сборка без доступа к API.
const FALLBACK_URL = "https://semitaskbot.pages.dev";
const APP_URL =
  process.env.EXPO_PUBLIC_APP_URL ||
  (Constants.expoConfig && Constants.expoConfig.extra
    ? Constants.expoConfig.extra.appUrl
    : "") ||
  FALLBACK_URL;

/** Хост приложения: всё остальное — «внешняя» ссылка. */
function hostOf(url) {
  const withoutScheme = url.replace(/^[a-z]+:\/\//i, "");
  return withoutScheme.split("/")[0].toLowerCase();
}

const APP_HOST = hostOf(APP_URL);

export default function App() {
  const web = useRef(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  // Аппаратная «назад» на Android: сначала история внутри приложения, и
  // только потом выход. Иначе человек закрывал бы приложение с любого экрана.
  useEffect(() => {
    if (Platform.OS !== "android") return undefined;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (web.current) {
        web.current.goBack();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, []);

  const openExternal = useCallback((url) => {
    Linking.openURL(url).catch(() => undefined);
  }, []);

  /**
   * Оставляем внутри приложения только свой домен. Письма поддержки, карты,
   * Telegram и любые внешние адреса открываются системно: в WebView у них нет
   * ни адресной строки, ни способа вернуться.
   */
  const onShouldStartLoadWithRequest = useCallback(
    (request) => {
      const url = request.url || "";
      if (url.startsWith("about:") || url.startsWith("data:")) return true;
      if (hostOf(url) === APP_HOST) return true;
      openExternal(url);
      return false;
    },
    [openExternal],
  );

  const retry = () => {
    setFailed(false);
    setLoading(true);
    if (web.current) web.current.reload();
  };

  return (
    <View style={styles.root}>
      <StatusBar style="auto" />
      {failed ? (
        <View style={styles.center}>
          <Text style={styles.title}>Нет связи с приложением</Text>
          <Text style={styles.text}>
            Проверьте интернет и попробуйте снова. Если не помогает — откройте
            приложение ещё раз: вход сохранится.
          </Text>
          <Pressable
            onPress={retry}
            accessibilityRole="button"
            style={styles.button}
          >
            <Text style={styles.buttonText}>Повторить</Text>
          </Pressable>
          <Text style={styles.hint}>{APP_HOST}</Text>
        </View>
      ) : (
        <WebView
          ref={web}
          source={{ uri: APP_URL }}
          originWhitelist={["*"]}
          javaScriptEnabled
          domStorageEnabled
          sharedCookiesEnabled
          allowsBackForwardNavigationGestures
          allowsInlineMediaPlayback
          mediaPlaybackRequiresUserAction={false}
          onShouldStartLoadWithRequest={onShouldStartLoadWithRequest}
          onLoadStart={() => setLoading(true)}
          onLoadEnd={() => setLoading(false)}
          onError={() => {
            setLoading(false);
            setFailed(true);
          }}
          onHttpError={(event) => {
            // 5xx — это «приложение не отвечает», а не рабочая страница
            // ошибки: показываем свой экран с повтором.
            const code = event.nativeEvent.statusCode;
            if (code >= 500) setFailed(true);
          }}
          setSupportMultipleWindows={false}
          textZoom={100}
          style={styles.web}
        />
      )}

      {loading && !failed && (
        <View pointerEvents="none" style={styles.loader}>
          <ActivityIndicator size="large" />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#ffffff",
  },
  web: {
    flex: 1,
    backgroundColor: "#ffffff",
  },
  loader: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    paddingTop: Platform.OS === "android" ? StatusBar.currentHeight || 0 : 0,
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 28,
    paddingTop: Platform.OS === "android" ? StatusBar.currentHeight || 0 : 0,
  },
  title: {
    fontSize: 18,
    fontWeight: "600",
    color: "#111111",
    textAlign: "center",
  },
  text: {
    marginTop: 8,
    fontSize: 14,
    lineHeight: 20,
    color: "#666666",
    textAlign: "center",
  },
  button: {
    marginTop: 20,
    minHeight: 48,
    paddingHorizontal: 24,
    borderRadius: 14,
    backgroundColor: "#2481cc",
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 15,
    fontWeight: "600",
  },
  hint: {
    marginTop: 16,
    fontSize: 11,
    color: "#999999",
  },
});
