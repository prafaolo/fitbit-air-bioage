import { NavLink, Route, Routes } from "react-router-dom";

import { Connection } from "./pages/Connection";
import { Dashboard } from "./pages/Dashboard";
import { ProfilePage } from "./pages/Profile";

export function App() {
  return (
    <div className="app">
      <nav>
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/profile">Profile</NavLink>
        <NavLink to="/connection">Connection</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/connection" element={<Connection />} />
        </Routes>
      </main>
    </div>
  );
}
