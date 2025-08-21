import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-new-secret-key!'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Game Management ---
games = {}
# The board is now bigger!
BOARD_SIZE = 12

class Game:
    """A class to represent the state and logic of a single SOS game."""
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}  # {sid: 'Player 1', sid: 'Player 2'}
        self.board = [['' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.turn = 'Player 1'
        self.scores = {'Player 1': 0, 'Player 2': 0}
        self.game_over = False
        self.winner = None
        self.last_sos_lines = []

    def add_player(self, sid):
        """Adds a player to the game if there's space."""
        if len(self.players) < 2:
            player_number = f"Player {len(self.players) + 1}"
            self.players[sid] = player_number
            return player_number
        return None

    def remove_player(self, sid):
        """Removes a player. Returns the remaining player if there is one."""
        remaining_player_id = None
        if sid in self.players:
            leaving_player = self.players[sid]
            # Find the other player
            for p_sid, p_num in self.players.items():
                if p_sid != sid:
                    remaining_player_id = p_num
            del self.players[sid]
        
        if not self.players:
            return None # Game can be deleted
        return remaining_player_id

    def make_move(self, player_sid, move_data):
        """Processes a player's move."""
        player = self.players.get(player_sid)
        if not player or player != self.turn or self.game_over:
            return False

        row, col, letter = move_data['row'], move_data['col'], move_data['letter']

        if self.board[row][col] == '':
            self.board[row][col] = letter
            points, lines = self._check_for_sos(row, col)

            if points > 0:
                self.scores[player] += points
                self.last_sos_lines = lines
            else:
                self.turn = 'Player 2' if self.turn == 'Player 1' else 'Player 1'
                self.last_sos_lines = []

            self._check_game_over()
            return True
        return False

    def _check_for_sos(self, r, c):
        """Robust check for 'SOS' patterns. Returns points and winning line coordinates."""
        points = 0
        lines = []
        if self.board[r][c] != 'O':
            return 0, []
            
        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
        for dr, dc in directions:
            s1_pos = (r - dr, c - dc)
            s2_pos = (r + dr, c + dc)
            if (0 <= s1_pos[0] < BOARD_SIZE and 0 <= s1_pos[1] < BOARD_SIZE and
                0 <= s2_pos[0] < BOARD_SIZE and 0 <= s2_pos[1] < BOARD_SIZE and
                self.board[s1_pos[0]][s1_pos[1]] == 'S' and
                self.board[s2_pos[0]][s2_pos[1]] == 'S'):
                points += 1
                lines.append([s1_pos, (r, c), s2_pos])
        return points, lines

    def _check_game_over(self):
        """Checks if the board is full and determines a winner."""
        if all(cell != '' for row in self.board for cell in row):
            self.game_over = True
            if self.scores['Player 1'] > self.scores['Player 2']:
                self.winner = 'Player 1'
            elif self.scores['Player 2'] > self.scores['Player 1']:
                self.winner = 'Player 2'
            else:
                self.winner = 'Draw'

    def declare_winner_on_disconnect(self, winning_player):
        """Sets the game state when a player leaves."""
        self.game_over = True
        self.winner = winning_player

    def get_state(self, sid=None):
        """Returns the current state of the game."""
        return {
            'board_size': BOARD_SIZE,
            'room_id': self.room_id,
            'board': self.board,
            'turn': self.turn,
            'scores': self.scores,
            'game_over': self.game_over,
            'winner': self.winner,
            'your_player_id': self.players.get(sid),
            'players_connected': len(self.players),
            'last_sos_lines': self.last_sos_lines
        }

def generate_room_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_game')
def handle_create_game():
    sid = request.sid
    room_id = generate_room_id()
    while room_id in games:
        room_id = generate_room_id()
    
    games[room_id] = Game(room_id)
    join_room(room_id)
    games[room_id].add_player(sid)
    emit('update_game', games[room_id].get_state(sid))

@socketio.on('join_game')
def handle_join_game(data):
    sid = request.sid
    room_id = data.get('room_id', '').upper()
    if room_id not in games:
        return emit('error', {'message': 'Room not found.'})
    
    game = games[room_id]
    if game.add_player(sid):
        join_room(room_id)
        socketio.emit('update_game', game.get_state(), to=room_id)
    else:
        emit('error', {'message': 'This room is already full.'})

@socketio.on('make_move')
def handle_make_move(data):
    sid = request.sid
    room_id = data.get('room_id')
    if room_id in games:
        game = games[room_id]
        if game.make_move(sid, data):
            socketio.emit('update_game', game.get_state(), to=room_id)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    for room_id, game in list(games.items()):
        if sid in game.players:
            remaining_player = game.remove_player(sid)
            if not remaining_player:
                # Last player left, so delete the game
                del games[room_id]
                print(f"Room {room_id} closed.")
            else:
                # A player is left, so they win by default
                if not game.game_over:
                    game.declare_winner_on_disconnect(remaining_player)
                    socketio.emit('notification', {'message': 'Opponent disconnected. You win!'}, to=room_id)
                    socketio.emit('update_game', game.get_state(), to=room_id)
            break

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')