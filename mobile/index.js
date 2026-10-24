import { registerRootComponent } from "expo";

import App from "./App";

// `registerRootComponent` сам ставит приложение в корень: и в Expo Go, и в
// нативной сборке точка входа одна, поэтому здесь нет ветки «это dev».
registerRootComponent(App);
