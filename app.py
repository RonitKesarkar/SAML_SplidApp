import os
from flask import Flask, render_template, request, redirect, flash, session, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from functools import wraps
from sqlalchemy.dialects.postgresql import ARRAY
from authlib.integrations.flask_client import OAuth

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:password@localhost:5432/splid_app'

# FIX: Fallback to environment variables to protect credentials
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret')

app.config['SESSION_COOKIE_NAME'] = 'splid_session'
app.config['SESSION_COOKIE_DOMAIN'] = 'localhost'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

db = SQLAlchemy(app)

# ---------------- AUTH0 CONFIG ----------------
AUTH0_DOMAIN = "dev-l33lvc1b46irpeqd.us.auth0.com"
AUTH0_CLIENT_ID = "rXq1PEDsPmnWnxnAPC6Xo8MC0WMEdOAl"
AUTH0_CLIENT_SECRET = os.environ.get('AUTH0_CLIENT_SECRET', '2Sl8ZvcCKqp3vIzCyBrTxjBtMsekSmyNVUzzZLdoYO3dnmFSKcF7yg7IUpcrnNt3')

oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=AUTH0_CLIENT_ID,
    client_secret=AUTH0_CLIENT_SECRET,
    api_base_url=f'https://{AUTH0_DOMAIN}',
    access_token_url=f'https://{AUTH0_DOMAIN}/oauth/token',
    authorize_url=f'https://{AUTH0_DOMAIN}/authorize',
    client_kwargs={
        'scope': 'openid profile email',
        'leeway': 120
    },
    server_metadata_url=f'https://{AUTH0_DOMAIN}/.well-known/openid-configuration'
)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login')
def login():
    return auth0.authorize_redirect(redirect_uri="http://localhost:5000/callback")

@app.route('/callback')
def callback():
    try:
        token = auth0.authorize_access_token()
        session['user'] = token.get('userinfo')
        return redirect(url_for('create_group'))
    except Exception as e:
        print("--- AUTHLIB DETECTED A LOGIN FAILURE ERROR: ---", str(e))
        flash("Login signature failed.")
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(f"https://{AUTH0_DOMAIN}/v2/logout?client_id={AUTH0_CLIENT_ID}&returnTo=http://localhost:5000/")

# ---------------- MODELS ----------------
class Group(db.Model):
    __tablename__ = 'group'
    __table_args__ = {'schema': 'splid_app'}
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(20))
    type = db.Column(db.String(10))
    date = db.Column(db.DateTime(timezone=True))

class Member(db.Model):
    __tablename__ = 'member'
    __table_args__ = {'schema': 'splid_app'}
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('splid_app.group.id', ondelete='CASCADE'))
    name = db.Column(db.String, nullable=False)
    paid = db.Column(db.Float, default=0.0)
    expense = db.Column(db.Float, default=0.0)
    balance = db.Column(db.Float, default=0.0)

class Expense(db.Model):
    __tablename__ = 'expense'
    __table_args__ = {'schema': 'splid_app'}
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('splid_app.group.id', ondelete='CASCADE'))
    name = db.Column(db.String, nullable=False)
    amt = db.Column(db.Float, nullable=False)
    paid_by = db.Column(db.Integer, db.ForeignKey('splid_app.member.id', ondelete='CASCADE'))
    paid_for = db.Column(ARRAY(db.Integer))
    date = db.Column(db.DateTime(timezone=True))

# ---------------- SECURED LEDGER ROUTES ----------------
@app.route('/', methods=['GET', 'POST'])
@login_required
def create_group():
    if request.method == 'POST':
        db.session.add(Group(
            title=request.form["title"],
            type=request.form["type"],
            date=datetime.now(timezone.utc)
        ))
        db.session.commit()
        return redirect("/")
    return render_template("index.html", allGroups=Group.query.all())

@app.route('/enter_group/<int:id>', methods=['GET'])
@login_required
def enter_group(id):
    group = Group.query.get_or_404(id)
    members = Member.query.filter_by(group_id=id).all()
    expenses = Expense.query.filter_by(group_id=id).all()
    paid_by, paid_for = [], []
    for exp in expenses:
        payer = Member.query.get(exp.paid_by)
        paid_by.append(payer.name if payer else "Unknown")
        names = []
        for mid in (exp.paid_for or []):
            member = Member.query.get(mid)
            if member:
                names.append(member.name)
        paid_for.append(names)
    return render_template("group.html", group=group, members=members, expenses=expenses, paid_by=paid_by, paid_for=paid_for)

@app.route('/back_to_group/<int:id>')
@login_required
def back_to_group(id):
    return redirect(f"/enter_group/{id}")

@app.route('/back_to_index')
@login_required
def back_to_index():
    return redirect("/")

@app.route('/change_name/<int:id>', methods=['GET', 'POST'])
@login_required
def change_name(id):
    group = Group.query.get_or_404(id)
    if request.method == 'POST':
        group.title = request.form["title"]
        group.type = request.form["type"]
        db.session.commit()
        return redirect(f"/enter_group/{id}")
    return render_template("update.html", group=group)

@app.route('/delete_group/<int:id>')
@login_required
def delete_group(id):
    Expense.query.filter_by(group_id=id).delete()
    Member.query.filter_by(group_id=id).delete()
    Group.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect("/")

@app.route('/add_member/<int:id>', methods=['GET', 'POST'])
@login_required
def add_member(id):
    if request.method == 'POST':
        name = request.form["name"].strip()
        if Member.query.filter_by(name=name, group_id=id).first():
            flash("Member exists")
            return redirect(f"/enter_group/{id}")
        db.session.add(Member(name=name, group_id=id))
        db.session.commit()
        return redirect(f"/enter_group/{id}")
    return render_template("member.html", group=Group.query.get_or_404(id))

@app.route('/update_member/<int:id>', methods=['GET', 'POST'])
@login_required
def update_member(id):
    m = Member.query.get_or_404(id)
    if request.method == 'POST':
        name = request.form["name"].strip()
        existing_member = Member.query.filter(
            Member.name == name, Member.group_id == m.group_id, Member.id != m.id
        ).first()
        if existing_member:
            flash("Member already exists")
            return redirect(f"/update_member/{m.id}")
        m.name = name
        db.session.commit()
        flash("Member updated successfully")
        return redirect(f"/enter_group/{m.group_id}")
    return render_template("member_update.html", member=m, group=Group.query.get(m.group_id))

@app.route('/add_expense/<int:id>', methods=['GET', 'POST'])
@login_required
def add_expense(id):
    group = Group.query.get_or_404(id)
    members = Member.query.filter_by(group_id=id).all()
    if request.method == 'POST':
        try:
            name = request.form["name"]
            amt = round(float(request.form["amt"]), 2)
            payer = Member.query.filter_by(name=request.form["paid_by"], group_id=id).first()
            if not payer:
                flash("Invalid payer")
                return redirect(f"/enter_group/{id}")
            
            # FIX: Pull checkbox data using standard array list format via Member Database IDs
            paid_for_ids = request.form.getlist("paid_for_members")
            paid_for = [int(mid) for mid in paid_for_ids]
            
            if not paid_for:
                flash("Select at least one member")
                return redirect(f"/enter_group/{id}")
                
            share = round(amt / len(paid_for), 2)
            payer.paid = round(payer.paid + amt, 2)
            payer.balance = round(payer.balance + amt, 2)
            
            for m in members:
                if m.id in paid_for:
                    m.expense = round(m.expense + share, 2)
                    m.balance = round(m.balance - share, 2)
                    
            db.session.add(Expense(
                name=name, group_id=id, amt=amt, paid_by=payer.id, paid_for=paid_for, date=datetime.now(timezone.utc)
            ))
            db.session.commit()
            return redirect(f"/enter_group/{id}")
        except Exception:
            db.session.rollback()
            flash("Error adding expense")
            return redirect(f"/enter_group/{id}")
    return render_template("expense.html", group=group, members=members)

@app.route('/change_expense/<int:id>', methods=['GET', 'POST'])
@login_required
def change_expense(id):
    exp = Expense.query.get_or_404(id)
    group = Group.query.get_or_404(exp.group_id)
    members = Member.query.filter_by(group_id=exp.group_id).all()
    if request.method == 'POST':
        try:
            old_payer = Member.query.get(exp.paid_by)
            if old_payer:
                old_payer.paid = round(old_payer.paid - exp.amt, 2)
                old_payer.balance = round(old_payer.balance - exp.amt, 2)
            old_share = round(exp.amt / len(exp.paid_for), 2) if exp.paid_for else 0
            for mid in (exp.paid_for or []):
                m = Member.query.get(mid)
                if m:
                    m.expense = round(m.expense - old_share, 2)
                    m.balance = round(m.balance + old_share, 2)
            
            amt = round(float(request.form["amt"]), 2)
            name = request.form["name"]
            
            # FIX: Use key value arrays rather than looping over variable parameters
            paid_for_ids = request.form.getlist("paid_for_members")
            paid_for = [int(mid) for mid in paid_for_ids]
            
            if not paid_for:
                flash("Select at least one member")
                return redirect(f"/enter_group/{exp.group_id}")

            new_payer = Member.query.filter_by(name=request.form["paid_by"], group_id=exp.group_id).first()
            if not new_payer:
                flash("Invalid payer")
                return redirect(f"/enter_group/{exp.group_id}")

            new_share = round(amt / len(paid_for), 2)
            new_payer.paid = round(new_payer.paid + amt, 2)
            new_payer.balance = round(new_payer.balance + amt, 2)
            for m in members:
                if m.id in paid_for:
                    m.expense = round(m.expense + new_share, 2)
                    m.balance = round(m.balance - new_share, 2)
                    
            exp.name = name
            exp.amt = amt
            exp.paid_by = new_payer.id
            exp.paid_for = paid_for
            exp.date = datetime.now(timezone.utc)
            db.session.commit()
            return redirect(f"/enter_group/{exp.group_id}")
        except Exception:
            db.session.rollback()
            flash("Error updating expense")
            return redirect(f"/enter_group/{exp.group_id}")
            
    current_payer = Member.query.get(exp.paid_by)
    return render_template("expense_update.html", expense=exp, group=group, members=members, current_payer_name=current_payer.name if current_payer else "")

@app.route('/delete_expense/<int:id>')
@login_required
def delete_expense(id):
    exp = Expense.query.get_or_404(id)
    group_id = exp.group_id
    try:
        payer = Member.query.get(exp.paid_by)
        if payer:
            payer.paid = round(payer.paid - exp.amt, 2)
            payer.balance = round(payer.balance - exp.amt, 2)
        share = round(exp.amt / len(exp.paid_for), 2) if exp.paid_for else 0
        for mid in (exp.paid_for or []):
            m = Member.query.get(mid)
            if m:
                m.expense = round(m.expense - share, 2)
                m.balance = round(m.balance + share, 2)
        db.session.delete(exp)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Error deleting expense")
    return redirect(f"/enter_group/{group_id}")

# ---------------- FIX: ADDED MISSING ROUTE LOGIC FOR SUGGESTIONS ----------------
@app.route('/suggested_payments/<int:id>')
@login_required
def suggested_payments(id):
    group = Group.query.get_or_404(id)
    members = Member.query.filter_by(group_id=id).all()
    
    # Basic greedy algorithm for calculating optimal debt settlement distributions
    debtors = sorted([[m.id, m.name, m.balance] for m in members if m.balance < -0.01], key=lambda x: x[2])
    creditors = sorted([[m.id, m.name, m.balance] for m in members if m.balance > 0.01], key=lambda x: x[2], reverse=True)
    
    payments = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debtor_name, d_bal = debtors[i]
        creditor_id, creditor_name, c_bal = creditors[j]
        
        amount_to_pay = min(abs(d_bal), c_bal)
        amount_to_pay = round(amount_to_pay, 2)
        
        if amount_to_pay > 0:
            text = f"{debtor_name} owes {creditor_name}: ${amount_to_pay:.2f}"
            url_params = f"{group.id}/{debtor_id}/{creditor_id}/{amount_to_pay}"
            payments.append((text, debtor_id, creditor_id, amount_to_pay))
            
        debtors[i][2] += amount_to_pay
        creditors[j][2] -= amount_to_pay
        
        if abs(debtors[i][2]) < 0.01: i += 1
        if abs(creditors[j][2]) < 0.01: j += 1
        
    return render_template("suggested_payments.html", group=group, payments=payments)

# ---------------- FIX: ADDED MISSING ROUTE LOGIC FOR TRANSACTIONS SETTLEMENT ----------------
@app.route('/save_payments/<int:group_id>/<int:debtor_id>/<int:creditor_id>/<float:amount>')
@login_required
def save_payments(group_id, debtor_id, creditor_id, amount):
    try:
        debtor = Member.query.get_or_404(debtor_id)
        creditor = Member.query.get_or_404(creditor_id)
        
        debtor.balance = round(debtor.balance + amount, 2)
        debtor.expense = round(debtor.expense - amount, 2)
        
        creditor.balance = round(creditor.balance - amount, 2)
        creditor.paid = round(creditor.paid - amount, 2)
        
        settle_exp = Expense(
            name="Settled up",
            group_id=group_id,
            amt=amount,
            paid_by=debtor.id,
            paid_for=[creditor.id],
            date=datetime.now(timezone.utc)
        )
        db.session.add(settle_exp)
        db.session.commit()
        flash("Payment settled successfully.")
    except Exception:
        db.session.rollback()
        flash("Error executing settlement sequence.")
    return redirect(f"/enter_group/{group_id}")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)