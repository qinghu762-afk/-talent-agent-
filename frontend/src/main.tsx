import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./styles.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#2457D6",
          colorText: "#192C43",
          colorSuccess: "#237A57",
          colorWarning: "#925513",
          colorError: "#B3303A",
          borderRadius: 6,
          fontFamily: "Segoe UI, Microsoft YaHei, sans-serif",
          controlHeight: 38,
          colorBgLayout: "#F5F7FA",
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
