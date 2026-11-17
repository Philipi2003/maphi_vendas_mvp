import { getApps, initializeApp } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";
import {
  GoogleAuthProvider,
  initializeAuth,
  inMemoryPersistence,
  signInWithPopup,
  signOut,
} from "https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js";

let firebaseAuth;

function getFirebaseAuth(config) {
  if (!firebaseAuth) {
    const app =
      getApps().find((candidate) => candidate.name === "[DEFAULT]") ??
      initializeApp(config);
    firebaseAuth = initializeAuth(app, { persistence: inMemoryPersistence });
  }
  return firebaseAuth;
}

export async function signInWithGoogle(config) {
  try {
    const auth = getFirebaseAuth(config);
    const result = await signInWithPopup(auth, new GoogleAuthProvider());
    const user = result.user;
    return {
      idToken: await user.getIdToken(),
      refreshToken: user.refreshToken,
      localId: user.uid,
      email: user.email,
      displayName: user.displayName,
    };
  } catch (error) {
    return {
      errorCode: error.code ?? "auth/unknown",
      errorMessage: error.message ?? "Não foi possível entrar com Google.",
    };
  }
}

export async function signOutFromGoogle() {
  if (firebaseAuth) {
    await signOut(firebaseAuth);
  }
}
