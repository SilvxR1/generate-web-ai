import { Route, Routes } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { Home } from "./routes/Home";
import { NewBusiness } from "./routes/NewBusiness";
import { Status } from "./routes/Status";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="businesses/new" element={<NewBusiness />} />
        <Route path="businesses/:businessId" element={<NewBusiness />} />
        <Route path="status" element={<Status />} />
      </Route>
    </Routes>
  );
}
