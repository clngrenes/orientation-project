const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const os = require('os');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*' }
});

app.use(express.static('public'));

// Direct device routes
const path = require('path');
app.get('/front', (req, res) => res.sendFile(path.join(__dirname, 'public/phone.html')));
app.get('/back', (req, res) => res.sendFile(path.join(__dirname, 'public/phone.html')));
app.get('/dashboard', (req, res) => res.sendFile(path.join(__dirname, 'public/dashboard.html')));

// Track connected phones
const phones = {};

io.on('connection', (socket) => {
  console.log(`Device connected: ${socket.id}`);
  // Send current status immediately to newly connected dashboard
  socket.emit('status', getStatus());

  socket.on('register', (role) => {
    phones[socket.id] = { role, detections: [] };
    console.log(`Phone registered as: ${role}`);
    io.emit('status', getStatus());
  });

  socket.on('detections', (data) => {
    if (phones[socket.id]) {
      phones[socket.id].detections = data.detections;
      phones[socket.id].stairDetected = data.stairDetected || false;
      phones[socket.id].floorObjects = data.floorObjects || [];
      phones[socket.id].timestamp = Date.now();
    }
    io.emit('spatial-update', buildSpatialMap());
  });

  // Forward camera frames to dashboard
  socket.on('frame', (data) => {
    io.emit('camera-frame', data);
  });

  // ToF sensor data from Pi bridge → forward to dashboard
  socket.on('tof-data', (data) => {
    io.emit('tof-update', data);
  });

  // Dashboard → device commands (vibrate / set-mode / manual-zone / sys)
  socket.on('dashboard-cmd', (data) => {
    // Forward to all connected devices (phones + bridge)
    io.emit('dashboard-cmd-broadcast', data);
  });

  // Voice agent events (voice_agent.py ↔ dashboard)
  socket.on('voice-query', (data) => {
    io.emit('voice-query-broadcast', data);   // show query in dashboard log
  });

  socket.on('voice-response', (data) => {
    io.emit('voice-response-broadcast', data); // show response in dashboard log
  });

  // Dashboard can trigger a remote voice query (Wizard of Oz)
  socket.on('voice-trigger', (data) => {
    io.emit('voice-trigger', data);           // relay to voice_agent.py
  });

  socket.on('disconnect', () => {
    delete phones[socket.id];
    console.log(`Device disconnected: ${socket.id}`);
    io.emit('status', getStatus());
  });
});

function getStatus() {
  const roles = Object.values(phones).map(p => p.role);
  return {
    frontConnected: roles.includes('front'),
    backConnected: roles.includes('back'),
    totalDevices: Object.keys(phones).length
  };
}

function buildSpatialMap() {
  const map = { front: [], back: [], timestamp: Date.now(),
    stairFront: false, stairBack: false,
    floorFront: [], floorBack: [] };
  for (const phone of Object.values(phones)) {
    if (phone.role === 'front') {
      map.front = phone.detections || [];
      map.stairFront = phone.stairDetected || false;
      map.floorFront = phone.floorObjects || [];
    } else if (phone.role === 'back') {
      map.back = phone.detections || [];
      map.stairBack = phone.stairDetected || false;
      map.floorBack = phone.floorObjects || [];
    }
  }
  return map;
}

function getLocalIP() {
  const interfaces = os.networkInterfaces();
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address;
      }
    }
  }
  return 'localhost';
}

const PORT = 3000;
server.listen(PORT, '0.0.0.0', () => {
  const ip = getLocalIP();
  console.log('\n========================================');
  console.log('  ORIENTATION Prototype Server Running');
  console.log('========================================');
  console.log(`\n  Local:  http://${ip}:${PORT}`);
  console.log('\n  Waiting for localtunnel URL...');
  console.log('  (phones use the loca.lt URL)');
  console.log('========================================\n');
});
