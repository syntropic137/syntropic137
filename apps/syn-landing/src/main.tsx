import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import Links from "./pages/Links";
import "@syn137/skyline-themes/all.css";
import "@syn137/skyline-themes/motion.css";
import "./globals.css";

const path = window.location.pathname;
const Page = path === "/links" ? Links : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>
);
