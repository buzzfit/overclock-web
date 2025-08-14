#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVERCLOCK — a neon cyberpunk circuit shooter in one Python file (pygame only)

Theme:
  You are a small‑but‑mighty digital hero in the matrix. Clear
  viruses, bugs, and worms while canceling hostile/natural power surges
  racing down the circuits.

Changes in this build:
  • OVERCLOCK is now a single BLAST: when full, press SHIFT to fire a huge
    surge in all four circuit directions at once. It pierces, cancels enemy/
    natural surges, and damages foes. One shot drains the meter completely.
  • Overclock is harder to earn (meter fills slower, bigger capacity).
  • No bright yellow overlay; instead the screen shakes for the blast window.
  • Enemy mitosis: when two enemies of the SAME TYPE touch, they spawn a third.
    (Throttled with a short cooldown and capped by MAX_ENEMIES_ON_FIELD.)

Controls:
  • Move: WASD / Arrow Keys
  • Aim: mouse (cardinal snap to the nearest circuit direction)
  • Fire surge: Left Mouse / SPACE
  • OVERCLOCK BLAST: SHIFT (when meter is full)
  • Pause: P
  • Toggle scanlines: M
  • Toggle bloom/shake: V
  • Restart (from game over): R
  • Quit: ESC

Dependencies: pygame  (pip install pygame)
"""

import math
import random
import sys
from array import array
from collections import deque

import pygame

# ---------- Window & Timing ----------
W, H = 960, 540
FPS = 60
TAU = getattr(math, "tau", 2.0 * math.pi)
CENTER = pygame.Vector2(W/2, H/2)

# ---------- Circuit/Grid ----------
GRID = 48                # spacing for circuit lines
JUNC_TOL = 6             # intersection tolerance in px

# ---------- Hero ----------
HERO_R = 8
HERO_SPEED = 260
HERO_IFRAMES = 1.0       # seconds of invulnerability after hit
HERO_SHOT_CD = 0.22      # seconds base cooldown
HERO_HP = 5

# ---------- Surges (bullets) ----------
SURGE_R = 5
SURGE_LEN = 1.9          # seconds lifetime
SURGE_SPEED_PLAYER = 560
SURGE_SPEED_ENEMY = 460
SURGE_SPEED_NATURAL = 520

# ---------- Overclock (BLAST) ----------
# Harder to earn:
OC_FILL_PER_CANCEL = 8       # meter from canceling enemy/natural surge (player shots only)
OC_FILL_PER_KILL   = 12      # meter from killing an enemy (player shots only)
OC_MAX = 200                 # total meter capacity
# Blast projectile stats:
OC_SURGE_R = 10
OC_SURGE_SPEED = 700
OC_SURGE_TTL = 1.6
OC_SURGE_DMG = 2
# Screen shake during the blast (no bright overlay)
OC_BLAST_SHAKE_TIME = 0.9
OC_BLAST_SHAKE_STRENGTH = 6.0

# ---------- Enemies ----------
VIRUS_BASE_R = 22
BUG_R = 14
WORM_R = 18

VIRUS_SPEED = 90
BUG_SPEED = 150
WORM_SPEED = 110

VIRUS_SHOOT_CD = (1.3, 1.9)
BUG_SHOOT_CD   = (0.85, 1.15)
WORM_SHOOT_CD  = (1.8, 2.4)

# ---------- Spawning / Waves ----------
SECTOR_START_ENEMIES = (2, 2, 1)  # (virus, bug, worm)
NAT_SURGE_EVERY = (2.4, 3.8)      # seconds between natural surge trains
MAX_ENEMIES_ON_FIELD = 18         # hard cap, including mitosis spawns

# ---------- VFX ----------
FANCY_VFX_DEFAULT = True
SCANLINES_DEFAULT = True
SHAKE_DECAY = 40.0
SHAKE_HIT = 3.5
SHAKE_SHOOT = 1.0
BLOOM_DOWNSCALE = 2

# ---------- Colors ----------
VERY_DARK   = (10, 12, 16)
GRID_DARK   = (24, 28, 36)
GRID_GLOW   = (38, 200, 220)
NEON_CYAN   = (0, 255, 222)
NEON_PURPLE = (242, 64, 255)
NEON_YELLOW = (255, 241, 84)
NEON_PINK   = (255, 100, 180)
NEON_GREEN  = (64, 255, 128)
HUD_WHITE   = (235, 238, 245)
HOSTILE_RED = (255, 70, 70)
NAT_ORANGE  = (255, 170, 40)

# ---------- Helpers ----------
def clamp(v, a, b):
    return a if v < a else b if v > b else v

def near_grid(v, spacing=GRID, tol=JUNC_TOL):
    return abs(v - round(v/spacing)*spacing) <= tol

def at_intersection(p):
    return near_grid(p.x) and near_grid(p.y)

def snap_axis(p, dirv):
    """Snap position to nearest complementary grid line (stay on 'wire')."""
    xg = round(p.x / GRID) * GRID
    yg = round(p.y / GRID) * GRID
    if abs(dirv.x) > 0:    # moving horiz -> lock Y
        p.y = yg
    if abs(dirv.y) > 0:    # moving vert -> lock X
        p.x = xg

def cardinal_from(v):
    if v.length_squared() == 0:
        return pygame.Vector2(1, 0)
    if abs(v.x) >= abs(v.y):
        return pygame.Vector2(1 if v.x >= 0 else -1, 0)
    else:
        return pygame.Vector2(0, 1 if v.y >= 0 else -1)

def rand_between(a_b):
    return random.uniform(a_b[0], a_b[1])

# ---------- Tiny tone synth (no numpy) ----------
def make_tone(freq=440.0, duration=0.08, volume=0.45, samplerate=22050):
    n = int(duration * samplerate)
    amp = int(32767 * max(0.0, min(1.0, volume)))
    buf = array("h", [0] * n)
    two_pi_f = 2.0 * math.pi * freq
    for i in range(n):
        s = int(amp * math.sin(two_pi_f * (i / samplerate)))
        buf[i] = s
    return pygame.mixer.Sound(buffer=buf.tobytes())

def make_dual_tone(f1=440, f2=660, duration=0.09, volume=0.5, samplerate=22050):
    n = int(duration * samplerate)
    amp = int(32767 * max(0.0, min(1.0, volume))) // 2
    buf = array("h", [0] * n)
    two_pi_1 = 2.0 * math.pi * f1
    two_pi_2 = 2.0 * math.pi * f2
    for i in range(n):
        s = int(amp * math.sin(two_pi_1 * (i / samplerate))) + int(amp * math.sin(two_pi_2 * (i / samplerate)))
        buf[i] = s
    return pygame.mixer.Sound(buffer=buf.tobytes())

# ---------- Visual helpers ----------
def make_scanlines(w, h, spacing=4, alpha=28):
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(0, h, spacing):
        pygame.draw.line(surf, (0, 0, 0, alpha), (0, y), (w, y))
    return surf

def draw_neon_text(surf, text, font, pos, color, glow_color=None):
    if glow_color is None:
        glow_color = color
    g = font.render(text, True, glow_color)
    for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
        surf.blit(g, (pos[0] + dx, pos[1] + dy))
    t = font.render(text, True, color)
    surf.blit(t, pos)

class Particle:
    def __init__(self, pos, vel, life, color, size=2):
        self.pos = pygame.Vector2(pos)
        self.vel = pygame.Vector2(vel)
        self.life = life
        self.age = 0.0
        self.color = color
        self.size = size
    def update(self, dt):
        self.age += dt
        self.pos += self.vel * dt
        self.vel *= 0.985
        return self.age < self.life
    def draw(self, surf):
        t = clamp(1.0 - self.age / self.life, 0.0, 1.0)
        r = int(clamp(self.color[0] * t + 5 * t, 0, 255))
        g = int(clamp(self.color[1] * t + 5 * t, 0, 255))
        b = int(clamp(self.color[2] * t + 5 * t, 0, 255))
        a = int(clamp(255 * t, 0, 255))
        col = (r, g, b, a)
        s = max(1, int(self.size))
        ps = pygame.Surface((s * 2, s * 2), pygame.SRCALPHA)
        pygame.draw.circle(ps, col, (s, s), s)
        surf.blit(ps, (int(self.pos.x - s), int(self.pos.y - s)))

# ---------- Audio ----------
class SFX:
    def __init__(self):
        self.enabled = False
        try:
            pygame.mixer.pre_init(22050, -16, 1, 256)
            pygame.mixer.init()
            self.enabled = pygame.mixer.get_init() is not None
        except Exception:
            self.enabled = False
        if not self.enabled:
            return
        try:
            self.s_menu      = make_dual_tone(420, 840, 0.12, 0.45)
            self.s_fire      = make_tone(980, 0.05, 0.5)
            self.s_enemyfire = make_tone(360, 0.06, 0.45)
            self.s_cancel    = make_dual_tone(700, 1200, 0.06, 0.5)
            self.s_hit       = make_tone(1150, 0.05, 0.55)
            self.s_hurt      = make_tone(160, 0.16, 0.5)
            self.s_explode   = make_dual_tone(260, 180, 0.12, 0.48)
            self.s_over_on   = make_dual_tone(900, 1200, 0.18, 0.5)
            self.s_over_off  = make_dual_tone(400, 220, 0.15, 0.45)
            self.s_win       = make_dual_tone(760, 1010, 0.2, 0.48)
            self.s_lose      = make_tone(120, 0.35, 0.45)
            self.s_natural   = make_tone(520, 0.05, 0.4)
            self.s_clone     = make_dual_tone(660, 990, 0.08, 0.5)
        except Exception:
            self.enabled = False

    def play(self, key):
        if not self.enabled: return
        m = {
            "menu": self.s_menu, "fire": self.s_fire, "enemyfire": self.s_enemyfire,
            "cancel": self.s_cancel, "hit": self.s_hit, "hurt": self.s_hurt,
            "explode": self.s_explode, "over_on": self.s_over_on, "over_off": self.s_over_off,
            "win": self.s_win, "lose": self.s_lose, "natural": self.s_natural,
            "clone": self.s_clone,
        }
        s = m.get(key)
        if s: s.play()

# ---------- Surges ----------
class Surge:
    __slots__ = ("pos","dir","speed","ttl","owner","color","r","trail","dmg","pierce")
    def __init__(self, pos, dirv, speed, owner, color, r=SURGE_R, ttl=SURGE_LEN, dmg=1, pierce=False):
        self.pos = pygame.Vector2(pos)
        self.dir = pygame.Vector2(cardinal_from(dirv))
        self.speed = speed
        self.owner = owner  # "player", "enemy", "natural", "oc"
        self.color = color
        self.r = r
        self.ttl = ttl
        self.dmg = dmg
        self.pierce = pierce
        self.trail = deque(maxlen=12)

    def update(self, dt):
        self.trail.append(self.pos.copy())
        self.pos += self.dir * self.speed * dt
        self.ttl -= dt
        # stay on a grid wire
        snap_axis(self.pos, self.dir)
        return self.ttl > 0 and (-20 < self.pos.x < W+20) and (-20 < self.pos.y < H+20)

    def draw(self, surf):
        # trail blend
        if len(self.trail) > 2:
            for i in range(1, len(self.trail)):
                a = self.trail[i - 1]
                b = self.trail[i]
                t = i / len(self.trail)
                col = (
                    int(self.color[0] * (1 - t) + 40 * t),
                    int(self.color[1] * (1 - t) + 40 * t),
                    int(self.color[2] * (1 - t) + 40 * t),
                )
                pygame.draw.line(surf, col, a, b, 2 if not self.pierce else 3)
        pygame.draw.circle(surf, self.color, (int(self.pos.x), int(self.pos.y)), self.r)

# ---------- Enemies ----------
class Enemy:
    def __init__(self, pos, r, hp, color):
        self.pos = pygame.Vector2(pos)
        self.r = r
        self.hp = hp
        self.color = color
        self.dir = random.choice([pygame.Vector2(1,0), pygame.Vector2(-1,0), pygame.Vector2(0,1), pygame.Vector2(0,-1)])
        self.turn_bias = 0.25
        self.shoot_t = rand_between((1.0, 1.6))
        self.spin = random.uniform(-2.0, 2.0)
        self.angle = random.random() * TAU
        self.rep_cd = 0.0  # mitosis cooldown

    def common_move(self, dt, speed):
        # Lock to wire and move; consider turning at intersections
        snap_axis(self.pos, self.dir)
        self.pos += self.dir * speed * dt
        # world bounds bounce
        if self.pos.x < 12 or self.pos.x > W-12:
            self.pos.x = clamp(self.pos.x, 12, W-12)
            self.dir.x *= -1; snap_axis(self.pos, self.dir)
        if self.pos.y < 12 or self.pos.y > H-12:
            self.pos.y = clamp(self.pos.y, 12, H-12)
            self.dir.y *= -1; snap_axis(self.pos, self.dir)
        # random turn at intersections
        if at_intersection(self.pos) and random.random() < self.turn_bias * dt * 60:
            if abs(self.dir.x) > 0:
                self.dir = random.choice([pygame.Vector2(0,1), pygame.Vector2(0,-1)])
            else:
                self.dir = random.choice([pygame.Vector2(1,0), pygame.Vector2(-1,0)])
            snap_axis(self.pos, self.dir)
        # mitosis cooldown
        if self.rep_cd > 0.0:
            self.rep_cd = max(0.0, self.rep_cd - dt)

    def take_damage(self, dmg):
        self.hp -= dmg
        return self.hp <= 0

    def draw_base(self, surf, width=2):
        # rotating diamond ring
        self.angle += self.spin / 60.0
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        r = self.r
        pts = []
        for px, py in ((0,-r),(r,0),(0,r),(-r,0)):
            x = px * ca - py * sa
            y = px * sa + py * ca
            pts.append((self.pos.x + x, self.pos.y + y))
        pygame.draw.polygon(surf, self.color, pts, width)
        pygame.draw.circle(surf, self.color, (int(self.pos.x), int(self.pos.y)), 2)

class Virus(Enemy):
    def __init__(self, pos, tier=2):
        r = VIRUS_BASE_R if tier==2 else (VIRUS_BASE_R-6 if tier==1 else VIRUS_BASE_R-10)
        hp = 3 if tier==2 else (2 if tier==1 else 1)
        color = NEON_PINK if tier>=1 else NEON_YELLOW
        super().__init__(pos, r, hp, color)
        self.tier = tier
        self.turn_bias = 0.18
        self.shoot_t = rand_between(VIRUS_SHOOT_CD)
    def update(self, dt, game):
        self.common_move(dt, VIRUS_SPEED)
        self.shoot_t -= dt
        shots = []
        if self.shoot_t <= 0.0:
            for d in [pygame.Vector2(1,0), pygame.Vector2(-1,0), pygame.Vector2(0,1), pygame.Vector2(0,-1)]:
                shots.append(Surge(self.pos, d, SURGE_SPEED_ENEMY, "enemy", HOSTILE_RED))
            self.shoot_t = rand_between(VIRUS_SHOOT_CD)
            game.sfx.play("enemyfire")
            game.add_shake(2.0)
        return shots
    def on_death(self):
        children = []
        if self.tier > 0:
            for _ in range(2):
                children.append(Virus(self.pos + pygame.Vector2(random.uniform(-10,10), random.uniform(-10,10)),
                                      tier=self.tier-1))
        return children
    def draw(self, surf):
        self.draw_base(surf, width=2)

class Bug(Enemy):
    def __init__(self, pos):
        super().__init__(pos, BUG_R, 2, NEON_GREEN)
        self.turn_bias = 0.45
        self.shoot_t = rand_between(BUG_SHOOT_CD)
    def update(self, dt, game):
        self.common_move(dt, BUG_SPEED)
        self.shoot_t -= dt
        shots = []
        if self.shoot_t <= 0.0:
            to_hero = game.hero.pos - self.pos
            d = cardinal_from(to_hero)
            shots.append(Surge(self.pos, d, SURGE_SPEED_ENEMY*1.05, "enemy", NEON_YELLOW))
            self.shoot_t = rand_between(BUG_SHOOT_CD)
            game.sfx.play("enemyfire")
        return shots
    def draw(self, surf):
        self.draw_base(surf, width=2)
        pygame.draw.circle(surf, self.color, (int(self.pos.x), int(self.pos.y)), 1)

class Worm(Enemy):
    def __init__(self, pos):
        super().__init__(pos, WORM_R, 4, NEON_PURPLE)
        self.turn_bias = 0.22
        self.shoot_t = rand_between(WORM_SHOOT_CD)
        self.drop_t = random.uniform(0.25, 0.55)
    def update(self, dt, game):
        self.common_move(dt, WORM_SPEED)
        shots = []
        self.drop_t -= dt
        if self.drop_t <= 0.0:
            game.spawn_glitch(self.pos)
            self.drop_t = random.uniform(0.35, 0.65)
        self.shoot_t -= dt
        if self.shoot_t <= 0.0:
            axis = 0 if abs(self.dir.x) > 0 else 1
            dirs = [pygame.Vector2(1,0), pygame.Vector2(-1,0)] if axis==0 else [pygame.Vector2(0,1), pygame.Vector2(0,-1)]
            for d in dirs:
                shots.append(Surge(self.pos, d, SURGE_SPEED_ENEMY*0.95, "enemy", HOSTILE_RED))
            self.shoot_t = rand_between(WORM_SHOOT_CD)
            game.sfx.play("enemyfire")
            game.add_shake(2.0)
        return shots
    def draw(self, surf):
        self.draw_base(surf, width=3)

# ---------- Hero ----------
class Hero:
    def __init__(self, pos):
        self.pos = pygame.Vector2(pos)
        self.vel = pygame.Vector2()
        self.r = HERO_R
        self.hp = HERO_HP
        self.ifr = 0.0
        self.cd = 0.0
        self.face = pygame.Vector2(1,0)
        self.oc_meter = 0  # 0..OC_MAX

    def alive(self):
        return self.hp > 0

    def hurt(self):
        if self.ifr > 0.0: return False
        self.hp -= 1
        self.ifr = HERO_IFRAMES
        return True

    def add_oc(self, v):
        self.oc_meter = clamp(self.oc_meter + v, 0, OC_MAX)

    def ready_overclock(self):
        return self.oc_meter >= OC_MAX

    def reset_overclock(self):
        self.oc_meter = 0

    def update(self, dt, keys):
        move = pygame.Vector2(0,0)
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:  move.x -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: move.x += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]:    move.y -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  move.y += 1
        if move.length_squared() > 0:
            move = move.normalize()
            self.pos += move * HERO_SPEED * dt
            self.face = cardinal_from(move)
        self.pos.x = clamp(self.pos.x, 12, W-12)
        self.pos.y = clamp(self.pos.y, 12, H-12)
        if self.ifr > 0.0: self.ifr = max(0.0, self.ifr - dt)
        if self.cd > 0.0:  self.cd = max(0.0, self.cd - dt)

    def can_shoot(self):
        return self.cd <= 0.0

    def shoot(self, aim_dir, overclock=False):
        # Overclock no longer affects normal shots; it's now a separate BLAST.
        self.cd = HERO_SHOT_CD
        dirv = cardinal_from(aim_dir if aim_dir.length_squared() > 0 else self.face)
        return Surge(self.pos, dirv, SURGE_SPEED_PLAYER, "player", NEON_CYAN, r=SURGE_R)

    def draw(self, surf):
        col = NEON_CYAN if (self.ifr <= 0 or int(self.ifr*20)%2==0) else (140, 160, 160)
        pygame.draw.circle(surf, col, (int(self.pos.x), int(self.pos.y)), self.r)
        tip = self.pos + self.face * (self.r + 4)
        pygame.draw.line(surf, col, self.pos, tip, 2)

# ---------- Natural surge trains ----------
class SurgeEmitter:
    """Spawns a short train of natural surges down one lane."""
    def __init__(self, row_or_col="row"):
        self.axis = row_or_col  # "row" (left<->right) or "col" (up<->down)
        self.fire_t = 0.0
        self.x_or_y = 0.0
        self.dir = pygame.Vector2(1,0)
        self.count = 0
        self.active = False

    def schedule(self):
        self.active = True
        self.count = random.randint(6, 10)
        if self.axis == "row":
            self.x_or_y = random.randint(2, (H-2)//GRID - 2) * GRID
            self.dir = pygame.Vector2(1,0) if random.random() < 0.5 else pygame.Vector2(-1,0)
        else:
            self.x_or_y = random.randint(2, (W-2)//GRID - 2) * GRID
            self.dir = pygame.Vector2(0,1) if random.random() < 0.5 else pygame.Vector2(0,-1)
        self.fire_t = 0.0

    def update(self, dt, game):
        if not self.active: return
        self.fire_t -= dt
        if self.fire_t <= 0.0 and self.count > 0:
            self.fire_t = 0.07  # packet spacing
            self.count -= 1
            if self.axis == "row":
                pos = pygame.Vector2(12 if self.dir.x > 0 else W-12, self.x_or_y)
            else:
                pos = pygame.Vector2(self.x_or_y, 12 if self.dir.y > 0 else H-12)
            game.surges.append(Surge(pos, self.dir, SURGE_SPEED_NATURAL, "natural", NAT_ORANGE))
            game.sfx.play("natural")
        if self.count <= 0:
            self.active = False

# ---------- Game ----------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("OVERCLOCK — Cyber Circuit Shooter")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 18, bold=True)
        self.bigfont = pygame.font.SysFont("arial", 48, bold=True)
        self.scanlines = make_scanlines(W, H)
        self.show_scans = SCANLINES_DEFAULT
        self.fancy_vfx = FANCY_VFX_DEFAULT
        self.sfx = SFX()

        self.world = pygame.Surface((W, H), pygame.SRCALPHA)
        self.hud_layer = pygame.Surface((W, H), pygame.SRCALPHA)

        self.state = "menu"  # "menu","play","paused","gameover","sectorclear"
        self.sector = 1
        self.score = 0
        self.highscore = 0

        self.hero = Hero(CENTER)
        self.enemies = []
        self.surges = []
        self.particles = []
        self.glitches = []  # hazard dots from Worms
        self.shake = 0.0

        # Overclock blast state
        self.oc_blast_timer = 0.0

        # Background "traces"
        self.trace_paths = self.build_traces()

        # Natural surge timing
        self.nat_timer = rand_between(NAT_SURGE_EVERY)
        self.emit_row = SurgeEmitter("row")
        self.emit_col = SurgeEmitter("col")

        self.sfx.play("menu")

    # ---- Traces & Background ----
    def build_traces(self):
        """Generate decorative 'copper traces' as polyline chains on the grid."""
        paths = []
        for _ in range(18):
            length = random.randint(3, 7)
            px = random.randint(1, (W-2)//GRID - 2) * GRID
            py = random.randint(1, (H-2)//GRID - 2) * GRID
            p = pygame.Vector2(px, py)
            dirv = random.choice([pygame.Vector2(1,0), pygame.Vector2(-1,0), pygame.Vector2(0,1), pygame.Vector2(0,-1)])
            pts = [p.copy()]
            for _ in range(length):
                if random.random() < 0.5:
                    dirv = pygame.Vector2(dirv.y, dirv.x)  # 90°
                    if random.random() < 0.5:
                        dirv *= -1
                p = p + dirv * GRID
                p.x = clamp(p.x, GRID, W-GRID)
                p.y = clamp(p.y, GRID, H-GRID)
                pts.append(p.copy())
            paths.append(pts)
        return paths

    def draw_circuit_bg(self, surf, t):
        surf.fill(VERY_DARK)
        col = GRID_DARK
        for x in range(GRID, W, GRID):
            pygame.draw.line(surf, col, (x, 0), (x, H), 1)
        for y in range(GRID, H, GRID):
            pygame.draw.line(surf, col, (0, y), (W, y), 1)
        for pts in self.trace_paths:
            for i in range(len(pts)-1):
                a, b = pts[i], pts[i+1]
                pygame.draw.line(surf, (30, 120, 160), a, b, 2)
            if len(pts) >= 2:
                segs = [(pts[i], pts[i+1]) for i in range(len(pts)-1)]
                total = sum((a.distance_to(b) for a,b in segs))
                mu = (t * 160) % max(total, 1)
                for a,b in segs:
                    seg_len = a.distance_to(b)
                    if mu <= seg_len:
                        d = (mu/seg_len) if seg_len > 0 else 0
                        px = a.x + (b.x - a.x)*d
                        py = a.y + (b.y - a.y)*d
                        pygame.draw.circle(surf, GRID_GLOW, (int(px), int(py)), 3)
                        break
                    mu -= seg_len

    # ---- Effects ----
    def add_shake(self, amount):
        if self.fancy_vfx:
            self.shake = min(12.0, self.shake + amount)

    def spark(self, pos, color, n=8):
        for _ in range(n):
            ang = random.random() * TAU
            spd = random.uniform(120, 260)
            vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * spd
            self.particles.append(Particle(pos, vel, random.uniform(0.25, 0.5), color, size=random.choice([1,2,2,3])))

    def spawn_glitch(self, pos):
        self.glitches.append([pos.copy(), 1.0])

    # ---- Sector / Spawning ----
    def build_sector(self, n_virus, n_bug, n_worm):
        self.enemies.clear()
        for _ in range(n_virus):
            self.enemies.append(Virus(self.random_grid_pos()))
        for _ in range(n_bug):
            self.enemies.append(Bug(self.random_grid_pos()))
        for _ in range(n_worm):
            self.enemies.append(Worm(self.random_grid_pos()))
        self.surges.clear()
        self.particles.clear()
        self.glitches.clear()
        self.hero = Hero(CENTER)
        self.nat_timer = rand_between(NAT_SURGE_EVERY)
        self.emit_row.active = False
        self.emit_col.active = False
        self.oc_blast_timer = 0.0

    def random_grid_pos(self):
        x = random.randint(2, (W-2)//GRID - 2) * GRID
        y = random.randint(2, (H-2)//GRID - 2) * GRID
        return pygame.Vector2(x, y)

    # ---- Game Loop ----
    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            if not self.handle_events():
                return
            if self.state == "paused":
                self.draw()
                continue
            self.update(dt)
            self.draw()

    # ---- Update ----
    def update(self, dt):
        if self.state == "menu":
            return
        if self.state in ("gameover", "sectorclear"):
            return

        keys = pygame.key.get_pressed()
        tnow = pygame.time.get_ticks() / 1000.0

        # Hero
        self.hero.update(dt, keys)

        # OVERCLOCK BLAST trigger
        if (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and self.hero.ready_overclock():
            self.fire_overclock_blast()
            # set shake loop during blast
            self.oc_blast_timer = OC_BLAST_SHAKE_TIME
            self.add_shake(OC_BLAST_SHAKE_STRENGTH)

        # Maintain shake during blast
        if self.oc_blast_timer > 0.0:
            self.oc_blast_timer = max(0.0, self.oc_blast_timer - dt)
            # refresh shake so it persists for the blast duration
            self.add_shake(OC_BLAST_SHAKE_STRENGTH * 0.75)

        # Normal firing
        mouse = pygame.Vector2(pygame.mouse.get_pos())
        aim = mouse - self.hero.pos
        if (pygame.mouse.get_pressed()[0] or keys[pygame.K_SPACE]) and self.hero.can_shoot():
            surge = self.hero.shoot(aim)
            self.surges.append(surge)
            self.sfx.play("fire")
            self.add_shake(SHAKE_SHOOT)

        # Natural surge scheduling
        if not (self.emit_row.active or self.emit_col.active):
            self.nat_timer -= dt
            if self.nat_timer <= 0.0:
                (self.emit_row if random.random()<0.5 else self.emit_col).schedule()
                self.nat_timer = rand_between(NAT_SURGE_EVERY)
        self.emit_row.update(dt, self)
        self.emit_col.update(dt, self)

        # Enemies update
        new_surges = []
        for e in list(self.enemies):
            shots = e.update(dt, self)
            if shots: new_surges.extend(shots)
        self.surges.extend(new_surges)

        # Enemy mitosis (same-type touch spawns a third)
        self.handle_enemy_mitosis()

        # Glitches decay
        self.glitches = [[p, max(0.0, a - dt*0.5)] for (p,a) in self.glitches if a - dt*0.5 > 0.0]

        # Surges move
        self.surges = [s for s in self.surges if s.update(dt)]

        # Particles update
        self.particles = [p for p in self.particles if p.update(dt)]

        # Collisions: surge vs surge (cancel)
        self.handle_surge_cancels()

        # Surge hits
        self.handle_surge_hits()

        # Glitch hazards vs hero
        for (gp, alpha) in self.glitches:
            if self.hero.pos.distance_to(gp) <= (self.hero.r + 7):
                if self.hero.hurt():
                    self.sfx.play("hurt")
                    self.add_shake(5.0)

        # Win/Lose
        if not self.hero.alive():
            self.state = "gameover"
            self.sfx.play("lose")
            self.highscore = max(self.highscore, self.score)
        elif len(self.enemies) == 0:
            self.state = "sectorclear"
            self.sfx.play("win")
            self.highscore = max(self.highscore, self.score)

        # shake decay
        if self.shake > 0.0:
            self.shake = max(0.0, self.shake - SHAKE_DECAY * (1.0/FPS))

    def fire_overclock_blast(self):
        pos = self.hero.pos.copy()
        dirs = [pygame.Vector2(1,0), pygame.Vector2(-1,0), pygame.Vector2(0,1), pygame.Vector2(0,-1)]
        for d in dirs:
            self.surges.append(
                Surge(pos, d, OC_SURGE_SPEED, "oc", NEON_YELLOW,
                      r=OC_SURGE_R, ttl=OC_SURGE_TTL, dmg=OC_SURGE_DMG, pierce=True)
            )
        self.hero.reset_overclock()
        self.sfx.play("over_on")
        self.spark(self.hero.pos, NEON_YELLOW, n=14)

    def handle_enemy_mitosis(self):
        n = len(self.enemies)
        to_add = []
        for i in range(n):
            ei = self.enemies[i]
            for j in range(i+1, n):
                ej = self.enemies[j]
                if type(ei) is not type(ej):
                    continue
                if ei.rep_cd > 0.0 or ej.rep_cd > 0.0:
                    continue
                if ei.pos.distance_to(ej.pos) <= (ei.r + ej.r):
                    if len(self.enemies) + len(to_add) >= MAX_ENEMIES_ON_FIELD:
                        continue
                    pos = (ei.pos + ej.pos) / 2 + pygame.Vector2(random.uniform(-6,6), random.uniform(-6,6))
                    # spawn same type
                    if isinstance(ei, Virus):
                        child = Virus(pos, tier=getattr(ei, "tier", 1))
                    elif isinstance(ei, Bug):
                        child = Bug(pos)
                    else:
                        child = Worm(pos)
                    child.rep_cd = 0.75
                    ei.rep_cd = 0.75
                    ej.rep_cd = 0.75
                    to_add.append(child)
                    self.sfx.play("clone")
                    self.spark(pos, (180, 220, 255), 10)
        if to_add:
            self.enemies.extend(to_add)

    def handle_surge_cancels(self):
        dead = set()
        for i in range(len(self.surges)):
            if i in dead: continue
            si = self.surges[i]
            for j in range(i+1, len(self.surges)):
                if j in dead: continue
                sj = self.surges[j]
                # clash if one is player/oc and the other is enemy/natural
                def is_friend(o): return o in ("player", "oc")
                def is_foe(o):    return o in ("enemy", "natural")
                if (is_friend(si.owner) and is_foe(sj.owner)) or (is_friend(sj.owner) and is_foe(si.owner)):
                    if si.pos.distance_to(sj.pos) <= (si.r + sj.r + 1):
                        # If OVERCLOCK surge involved, it pierces (kill foe only)
                        if si.owner == "oc" and is_foe(sj.owner):
                            dead.add(j)
                        elif sj.owner == "oc" and is_foe(si.owner):
                            dead.add(i)
                        else:
                            dead.add(i); dead.add(j)
                        self.sfx.play("cancel")
                        self.spark((si.pos+sj.pos)/2, (140, 200, 255))
                        # Only normal player cancels feed the meter
                        if ("player" in (si.owner, sj.owner)):
                            self.hero.add_oc(OC_FILL_PER_CANCEL)
        if dead:
            self.surges = [s for k,s in enumerate(self.surges) if k not in dead]

    def handle_surge_hits(self):
        # Iterate on a copy; remove from original safely
        for s in list(self.surges):
            if s.owner in ("player", "oc"):
                # Enemy hit
                hit_any = False
                for e in list(self.enemies):
                    if e.pos.distance_to(s.pos) <= (e.r + s.r):
                        hit_any = True
                        died = e.take_damage(s.dmg)
                        self.sfx.play("hit")
                        self.spark(s.pos, NEON_CYAN if s.owner=="player" else NEON_YELLOW, 10)
                        if s.owner == "player":
                            self.score += 45
                            self.hero.add_oc(OC_FILL_PER_KILL)
                        else:
                            self.score += 35
                        if died:
                            self.sfx.play("explode")
                            self.spark(e.pos, e.color, 18)
                            self.enemies.remove(e)
                            if isinstance(e, Virus):
                                for child in e.on_death():
                                    if len(self.enemies) < MAX_ENEMIES_ON_FIELD:
                                        self.enemies.append(child)
                            self.score += 120 if s.owner=="player" else 90
                        if not s.pierce:
                            if s in self.surges:
                                self.surges.remove(s)
                            break
                # If it didn't hit anything, continue flying
                continue
            else:
                # Enemy or natural surge hitting hero
                if self.hero.pos.distance_to(s.pos) <= (self.hero.r + s.r):
                    if s in self.surges:
                        self.surges.remove(s)
                    if self.hero.hurt():
                        self.sfx.play("hurt")
                        self.add_shake(6.0)

    # ---- Draw ----
    def draw_hud(self, surf):
        status = f"Sector {self.sector}   •   Score {self.score}   •   High {self.highscore}"
        draw_neon_text(surf, status, self.font, (12, 10), HUD_WHITE)

        # Integrity (HP)
        x0, y0 = 12, 36
        for i in range(HERO_HP):
            col = NEON_PINK if i < self.hero.hp else (70, 60, 70)
            pygame.draw.rect(surf, col, pygame.Rect(x0 + i*18, y0, 14, 8))

        # Overclock meter
        oc = self.hero.oc_meter / OC_MAX
        pygame.draw.rect(surf, (30,30,38), pygame.Rect(W-202, 36, 190, 8))
        pygame.draw.rect(surf, NEON_YELLOW, pygame.Rect(W-202, 36, int(190*oc), 8))
        if self.hero.ready_overclock() and self.oc_blast_timer <= 0.0:
            label = "OVERCLOCK READY (SHIFT)"
            col = NEON_YELLOW
        elif self.oc_blast_timer > 0.0:
            label = "OVERCLOCK BLAST!"
            col = NEON_GREEN
        else:
            label = "CHARGING…"
            col = HUD_WHITE
        draw_neon_text(surf, label, self.font, (W-200, 48), col)

    def draw_menu(self, surf):
        title = "OVERCLOCK"
        tw = self.bigfont.size(title)[0]
        draw_neon_text(surf, title, self.bigfont, (W//2 - tw//2, H//2 - 86), NEON_CYAN, glow_color=NEON_PURPLE)
        draw_neon_text(surf, "Jack into the grid. Cancel hostile surges. Purge the system.",
                       self.font, (W//2 - 250, H//2 - 36), HUD_WHITE)
        draw_neon_text(surf, "Move: WASD/Arrows   •   Fire: LMB/SPACE   •   Overclock BLAST: SHIFT",
                       self.font, (W//2 - 300, H//2 - 12), (200, 220, 230))
        draw_neon_text(surf, "Press SPACE or CLICK to start",
                       self.font, (W//2 - 120, H//2 + 20), NEON_YELLOW)

    def draw_gameover(self, surf):
        title = "SYSTEM FAILURE"
        tw = self.bigfont.size(title)[0]
        draw_neon_text(surf, title, self.bigfont, (W//2 - tw//2, H//2 - 60), HOSTILE_RED)
        draw_neon_text(surf, f"Score {self.score}   •   Sector {self.sector}",
                       self.font, (W//2 - 90, H//2 - 10), HUD_WHITE)
        draw_neon_text(surf, "Press R to reboot", self.font, (W//2 - 70, H//2 + 20), NEON_YELLOW)

    def draw_sectorclear(self, surf):
        title = "SECTOR STABILIZED"
        tw = self.bigfont.size(title)[0]
        draw_neon_text(surf, title, self.bigfont, (W//2 - tw//2, H//2 - 60), NEON_GREEN)
        draw_neon_text(surf, f"Score {self.score}", self.font, (W//2 - 40, H//2 - 10), HUD_WHITE)
        draw_neon_text(surf, "Press SPACE / CLICK to proceed", self.font, (W//2 - 120, H//2 + 20), NEON_YELLOW)

    def draw(self):
        t = pygame.time.get_ticks()/1000.0

        # World layer
        self.world.fill((0,0,0,0))
        self.draw_circuit_bg(self.world, t)

        # Glitches
        for (gp, alpha) in self.glitches:
            a = int(200*alpha)
            ps = pygame.Surface((10,10), pygame.SRCALPHA)
            pygame.draw.rect(ps, (255, 120, 255, a), pygame.Rect(0,0,10,10))
            self.world.blit(ps, (gp.x-5, gp.y-5))

        # Surges
        for s in self.surges:
            s.draw(self.world)

        # Enemies
        for e in self.enemies:
            e.draw(self.world)

        # Hero
        if self.hero.alive():
            self.hero.draw(self.world)

        # HUD
        self.hud_layer.fill((0,0,0,0))
        if self.state == "menu":
            self.draw_menu(self.hud_layer)
        elif self.state == "play":
            self.draw_hud(self.hud_layer)
        elif self.state == "gameover":
            self.draw_hud(self.hud_layer)
            self.draw_gameover(self.hud_layer)
        elif self.state == "sectorclear":
            self.draw_hud(self.hud_layer)
            self.draw_sectorclear(self.hud_layer)
        elif self.state == "paused":
            draw_neon_text(self.hud_layer, "PAUSED", self.bigfont, (W//2 - 80, H//2 - 24), NEON_PURPLE)

        # Screen shake affects world, not HUD
        ox = oy = 0
        if self.fancy_vfx and self.shake > 0.0:
            ox = int(random.uniform(-1.0, 1.0) * self.shake)
            oy = int(random.uniform(-1.0, 1.0) * self.shake)

        self.screen.fill(VERY_DARK)
        self.screen.blit(self.world, (ox, oy))

        # Bloom
        if self.fancy_vfx:
            ds = BLOOM_DOWNSCALE
            glow = pygame.transform.smoothscale(self.world, (W//ds, H//ds))
            glow = pygame.transform.smoothscale(glow, (W, H))
            self.screen.blit(glow, (ox, oy), special_flags=pygame.BLEND_ADD)

        # No bright overclock overlay; shake covers the BLAST

        # HUD
        self.screen.blit(self.hud_layer, (0, 0))

        if self.show_scans:
            self.screen.blit(self.scanlines, (0, 0))

        pygame.display.flip()

    # ---- Input ----
    def handle_events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return False
                if e.key == pygame.K_p and self.state in ("play","paused"):
                    self.state = "paused" if self.state == "play" else "play"
                if e.key == pygame.K_v:
                    self.fancy_vfx = not self.fancy_vfx
                if e.key == pygame.K_m:
                    self.show_scans = not self.show_scans
                if e.key == pygame.K_r and self.state == "gameover":
                    self.score = 0
                    self.sector = 1
                    self.build_sector(*SECTOR_START_ENEMIES)
                    self.state = "play"
                if self.state == "menu" and e.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self.score = 0
                    self.sector = 1
                    self.build_sector(*SECTOR_START_ENEMIES)
                    self.state = "play"
                if self.state == "sectorclear" and e.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self.sector += 1
                    v, b, w = SECTOR_START_ENEMIES
                    add = self.sector // 2
                    self.build_sector(v+add, b+add, w + (1 if self.sector%3==0 else 0))
                    self.state = "play"
            if e.type == pygame.MOUSEBUTTONDOWN:
                if self.state == "menu" and e.button == 1:
                    self.score = 0
                    self.sector = 1
                    self.build_sector(*SECTOR_START_ENEMIES)
                    self.state = "play"
                if self.state == "sectorclear" and e.button == 1:
                    self.sector += 1
                    v, b, w = SECTOR_START_ENEMIES
                    add = self.sector // 2
                    self.build_sector(v+add, b+add, w + (1 if self.sector%3==0 else 0))
                    self.state = "play"
        return True

# ---------- Entry ----------
if __name__ == "__main__":
    try:
        Game().run()
    except KeyboardInterrupt:
        pass
