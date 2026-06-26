// frontend/assets/js/auth.js
//
// Handles all authentication state for RinSathi frontend.
//
// Responsibilities:
//   - Store and retrieve JWT token from localStorage
//   - Decode JWT payload (to read role without an API call)
//   - Logout (clear token + redirect)
//   - Check if current token is still valid (not expired)
//
// Every page loads this file first.
// Guard pages (guard.js) depend on functions defined here.

const API_BASE = "http://localhost:8000/api/v1";

// ── Token storage ─────────────────────────────────────────────────────────────
// We use a named key so it's easy to find and clear

const TOKEN_KEY = "rinsathi_jwt";
const USER_KEY  = "rinsathi_user";

function saveAuth(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function getUser() {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
}

function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

// ── JWT decode ────────────────────────────────────────────────────────────────
// We decode the payload locally to read role and expiry.
// We do NOT verify the signature here — that happens on the server.
// This is just for UI routing decisions.

function decodeJWT(token) {
    try {
        // JWT is three base64 parts separated by dots
        // The middle part (index 1) is the payload
        const base64 = token.split('.')[1];
        const json   = atob(base64.replace(/-/g, '+').replace(/_/g, '/'));
        return JSON.parse(json);
    } catch {
        return null;
    }
}

function isTokenExpired(token) {
    const payload = decodeJWT(token);
    if (!payload || !payload.exp) return true;
    // exp is in seconds, Date.now() is in milliseconds
    return payload.exp * 1000 < Date.now();
}

function isLoggedIn() {
    const token = getToken();
    if (!token) return false;
    if (isTokenExpired(token)) {
        clearAuth();  // Clean up expired token automatically
        return false;
    }
    return true;
}

function getUserRole() {
    const token = getToken();
    if (!token) return null;
    const payload = decodeJWT(token);
    return payload ? payload.role : null;
}

// ── Logout ────────────────────────────────────────────────────────────────────

function logout() {
    clearAuth();
    // Redirect based on what page we're on
    const path = window.location.pathname;
    if (path.includes('/officer/')) {
        window.location.href = '/auth/officer_login.html';
    } else {
        window.location.href = '/auth/login.html';
    }
}

// ── API helper ────────────────────────────────────────────────────────────────
// All fetch calls go through this function.
// It automatically adds the Authorization header.

async function apiFetch(endpoint, options = {}) {
    const token = getToken();

    const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...(options.headers || {})
    };

    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers
    });

    // If server returns 401, token is invalid — force logout
    if (response.status === 401) {
        clearAuth();
        window.location.href = '/auth/login.html';
        return;
    }

    return response;
}