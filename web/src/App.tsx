import { Route, Routes } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import Account from "./pages/Account";
import Activity from "./pages/Activity";
import { AuthPage } from "./pages/Auth";
import Discover from "./pages/Discover";
import { Genre, Genres } from "./pages/Genres";
import Home from "./pages/Home";
import Lab from "./pages/Lab";
import { Privacy, Terms } from "./pages/Legal";
import Movie from "./pages/Movie";
import SimilarAll from "./pages/SimilarAll";
import MyList from "./pages/MyList";
import Onboarding from "./pages/Onboarding";
import Person from "./pages/Person";
import SeriesFit from "./pages/SeriesFit";
import Missions from "./pages/Missions";
import TasteDna from "./pages/TasteDna";
import Search from "./pages/Search";
import StatsPage from "./pages/Stats";
import { PageMessage } from "./components/Loading";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Home />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/genres" element={<Genres />} />
        <Route path="/genres/:slug" element={<Genre />} />
        <Route path="/movie/:id" element={<Movie />} />
        <Route path="/movie/:id/similar" element={<SimilarAll />} />
        <Route path="/person/:id" element={<Person />} />
        <Route path="/my-list" element={<MyList />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/missions" element={<Missions />} />
        <Route path="/taste-dna" element={<TasteDna />} />
        <Route path="/search" element={<Search />} />
        <Route path="/series-fit" element={<SeriesFit />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/lab" element={<Lab />} />
        <Route path="/account" element={<Account />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="*" element={<PageMessage title="Page not found" />} />
      </Route>
    </Routes>
  );
}