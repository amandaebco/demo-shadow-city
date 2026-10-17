export const APP_CONFIG = {
  gcpProjectId: process.env.NEXT_PUBLIC_GCP_PROJECT_ID || "ebc-cloud-dev-03",
  firestoreDatabase: process.env.NEXT_PUBLIC_FIRESTORE_DATABASE || "shadow-city",
  orchestratorUrl: process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || "http://localhost:8080",
  googleMapsApiKey: process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "",
  jakartaCenter: {
    lat: -6.1754,
    lng: 106.8272,
    zoom: 11.4,
  },
} as const;

