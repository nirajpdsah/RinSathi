// frontend/assets/js/guard.js
//
// Route guard — protects pages from unauthorized access.
//
// How to use on any protected page:
//   <script src="/assets/js/auth.js"></script>
//   <script src="/assets/js/guard.js"></script>
//   <script>guardPage('client');</script>   ← or 'officer'
//
// What it does:
//   1. Checks if a JWT token exists in localStorage
//   2. Checks if the token has expired
//   3. Checks if the user's role matches the required role
//   4. Redirects to the correct login page if any check fails
//
// This runs before the page content loads — the user never
// sees a flash of protected content before being redirected.

function guardPage(requiredRole) {
    // Check 1: Is the user logged in at all?
    if (!isLoggedIn()) {
        if (requiredRole === 'officer') {
            window.location.href = '/auth/officer_login.html';
        } else {
            window.location.href = '/auth/login.html';
        }
        return false;
    }

    // Check 2: Does the user have the right role?
    const role = getUserRole();
    if (role !== requiredRole) {
        // Wrong role — redirect to their correct dashboard
        // A client trying to access officer pages goes to client dashboard
        // An officer trying to access client pages goes to officer dashboard
        if (role === 'officer') {
            window.location.href = '/templates/officer/dashboard.html';
        } else {
            window.location.href = '/templates/client/dashboard.html';
        }
        return false;
    }

    return true;
}

// Convenience: show the logged-in user's name in the navbar
// Call this after guardPage() passes
function showUserInfo(nameElementId) {
    const user = getUser();
    if (user && nameElementId) {
        const el = document.getElementById(nameElementId);
        if (el) el.textContent = user.full_name;
    }
}