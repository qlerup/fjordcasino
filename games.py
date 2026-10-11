"""Server-authoritative games. All amounts are fictional integer coins."""
import secrets

RNG = secrets.SystemRandom()
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
SLOTS = {
    'duck': {'name':'Andedammen', 'symbols':['duck-yellow','duck-mallard','duck-pink','duck-sailor','duck-crown','wild'], 'pays':[8,12,20,36,80,200]},
    'fruit': {'name':'Frugtfesten', 'symbols':['cherry','lemon','grape','watermelon','seven','wild'], 'pays':[8,12,20,36,80,200]},
    'cosmic': {'name':'Stjernestøv', 'symbols':['star','moon','planet','rocket','diamond','wild'], 'pays':[8,12,20,36,80,200]},
}
WEIGHTS = [30,25,20,15,8,2]
SLOT_BETS = [30,60,150,300,600]
TABLE_BETS = [20,50,100,200,500,1000]


class GameError(ValueError):
    pass


def require_int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise GameError(f'Vælg et helt antal mønter mellem {low} og {high}.')
    return value


def slot_payout(grid, machine, bet):
    symbols, pays = SLOTS[machine]['symbols'], SLOTS[machine]['pays']
    lines = []
    for i, line in enumerate(grid):
        normal = {symbol for symbol in line if symbol != 'wild'}
        if len(normal) <= 1:
            symbol = next(iter(normal), 'wild')
            amount = bet // 3 * pays[symbols.index(symbol)]
            lines.append({'row':i, 'symbol':symbol, 'payout':amount})
    return lines


def spin_slots(machine, bet, rng=RNG):
    if not isinstance(machine, str) or machine not in SLOTS or type(bet) is not int or bet not in SLOT_BETS:
        raise GameError('Vælg en spilleautomat og en gyldig indsats.')
    grid = [rng.choices(SLOTS[machine]['symbols'], weights=WEIGHTS, k=3) for _ in range(3)]
    lines = slot_payout(grid, machine, bet)
    return {'game':'slots', 'machine':machine, 'grid':grid, 'lines':lines,
            'bet':bet, 'payout':sum(line['payout'] for line in lines)}


def validate_roulette(bets):
    if not isinstance(bets, list) or not 1 <= len(bets) <= 20:
        raise GameError('Placér mellem 1 og 20 indsatser på bordet.')
    for bet in bets:
        if not isinstance(bet, dict):
            raise GameError('Ugyldig rouletteindsats.')
        require_int(bet.get('amount'), 10, 1000)
        kind, value = bet.get('kind'), bet.get('value')
        if not isinstance(kind, str):
            raise GameError('Ugyldig rouletteindsats.')
        allowed = {'color':('red','black'), 'parity':('even','odd'), 'range':('low','high')}
        if kind == 'number':
            require_int(value, 0, 36)
        elif kind in ('dozen','column'):
            require_int(value, 1, 3)
        elif kind not in allowed or value not in allowed[kind]:
            raise GameError('Ugyldig rouletteindsats.')
    total = sum(bet['amount'] for bet in bets)
    if total > 5000:
        raise GameError('Du kan højst satse 5.000 mønter pr. runde.')
    return total


def roulette_payout(number, bets):
    payouts = []
    for bet in bets:
        kind, value = bet['kind'], bet['value']
        win, multiplier = False, 2
        if kind == 'number':
            win, multiplier = number == value, 36
        elif number:
            if kind == 'color': win = (number in RED) == (value == 'red')
            if kind == 'parity': win = (number % 2 == 0) == (value == 'even')
            if kind == 'range': win = (number <= 18) == (value == 'low')
            if kind == 'dozen': win, multiplier = (number-1)//12+1 == value, 3
            if kind == 'column': win, multiplier = (number-1)%3+1 == value, 3
        payouts.append({**bet, 'payout':bet['amount']*multiplier if win else 0})
    return payouts


def spin_roulette(table, bets, rng=RNG):
    if table not in ('classic','duck'):
        raise GameError('Vælg et roulettebord.')
    total = validate_roulette(bets)
    number = rng.randrange(37)
    outcomes = roulette_payout(number, bets)
    return {'game':'roulette', 'table':table, 'number':number, 'color':'green' if not number else 'red' if number in RED else 'black',
            'bet':total, 'payout':sum(b['payout'] for b in outcomes), 'bets':outcomes}


def hand_value(cards):
    values = [min(card % 13 + 1, 10) for card in cards]
    total = sum(values)
    soft = 1 in values and total + 10 <= 21
    return total + 10 if soft else total, soft


def start_blackjack(bet, rng=RNG):
    if type(bet) is not int or bet not in TABLE_BETS:
        raise GameError('Vælg en gyldig blackjackindsats.')
    deck = list(range(52))*6
    rng.shuffle(deck)
    game = {'game':'blackjack', 'deck':deck, 'player':[], 'dealer':[], 'bet':bet,
            'status':'playing', 'payout':0, 'result':'', 'doubled':False, 'round_id':secrets.token_hex(16)}
    for _ in range(2):
        game['player'].append(deck.pop()); game['dealer'].append(deck.pop())
    player, _ = hand_value(game['player']); dealer, _ = hand_value(game['dealer'])
    if player == 21 or dealer == 21:
        game['status'] = 'finished'
        game['payout'] = bet if player == dealer else bet*5//2 if player == 21 else 0
        game['result'] = 'push' if player == dealer else 'blackjack' if player == 21 else 'dealer_blackjack'
    return game


def act_blackjack(game, action):
    if game['status'] != 'playing' or action not in ('hit','stand','double'):
        raise GameError('Denne handling er ikke mulig i den aktuelle runde.')
    if action == 'double':
        if len(game['player']) != 2 or game['doubled']:
            raise GameError('Du kan kun fordoble på dine første to kort.')
        game['bet'] *= 2; game['doubled'] = True
    if action in ('hit','double'):
        game['player'].append(game['deck'].pop())
    player, _ = hand_value(game['player'])
    if player > 21:
        game.update(status='finished', result='bust', payout=0)
    elif action in ('stand','double') or player == 21:
        while hand_value(game['dealer'])[0] < 17:
            game['dealer'].append(game['deck'].pop())
        dealer, _ = hand_value(game['dealer'])
        result = 'win' if dealer > 21 or player > dealer else 'push' if player == dealer else 'lose'
        game.update(status='finished', result=result, payout=game['bet']*({'win':2,'push':1,'lose':0}[result]))
    return game


def public_blackjack(game):
    if not game:
        return None
    active = game['status'] == 'playing'
    return {key:value for key,value in game.items() if key not in ('deck','dealer')} | {
        'dealer':[game['dealer'][0], None] if active else game['dealer'],
        'player_total':hand_value(game['player'])[0],
        'dealer_total':hand_value(game['dealer'][:1] if active else game['dealer'])[0],
        'can_double':active and len(game['player']) == 2 and not game['doubled'],
    }
