import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import "./index.css";
import { AppShell, Centered } from "./components/shell";
import { Skeleton, ToastProvider } from "./components/ui";
import { ApiError } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import Login from "./pages/Login";

const pages = {
  Home: () => import("./pages/Home"),
  Deals: () => import("./pages/Deals"),
  DealDetail: () => import("./pages/DealDetail"),
  Searches: () => import("./pages/Searches"),
  SearchDetail: () => import("./pages/SearchDetail"),
  NewSearch: () => import("./pages/NewSearch"),
  Wishlist: () => import("./pages/Wishlist"),
  Assistant: () => import("./pages/Assistant"),
  Budget: () => import("./pages/Budget"),
  Usage: () => import("./pages/Usage"),
  Settings: () => import("./pages/Settings"),
};
const Home = lazy(pages.Home);
const Deals = lazy(pages.Deals);
const DealDetail = lazy(pages.DealDetail);
const Searches = lazy(pages.Searches);
const SearchDetail = lazy(pages.SearchDetail);
const NewSearch = lazy(pages.NewSearch);
const Wishlist = lazy(pages.Wishlist);
const Assistant = lazy(pages.Assistant);
const Budget = lazy(pages.Budget);
const Usage = lazy(pages.Usage);
const SettingsPage = lazy(pages.Settings);

registerSW({ immediate: true });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});

function PageFallback() {
  return (
    <div className="space-y-4 pt-2">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

function Gate() {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <Centered>
        <Skeleton className="mx-auto h-8 w-32" />
      </Centered>
    );
  if (!user) return <Login />;
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route element={<AppShell preload={Object.values(pages)} />}>
          <Route index element={<Home />} />
          <Route path="deals" element={<Deals />} />
          <Route path="deals/:id" element={<DealDetail />} />
          <Route path="searches" element={<Searches />} />
          <Route path="searches/new" element={<NewSearch />} />
          <Route path="searches/:id" element={<SearchDetail />} />
          <Route path="wishlist" element={<Wishlist />} />
          <Route path="assistant" element={<Assistant />} />
          <Route path="assistant/:threadId" element={<Assistant />} />
          <Route path="budget" element={<Budget />} />
          <Route path="usage" element={<Usage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="settings/:tab" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <AuthProvider>
            <Gate />
          </AuthProvider>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
