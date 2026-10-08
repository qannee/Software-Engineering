import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './style.css';
import './map.css';
import './mobile.css';

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>);
