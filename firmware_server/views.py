from firmware_server import app
from firmware_server.database import *
from firmware_server.utils import *
from flask import (
    render_template,
    redirect,
    request,
    url_for
)
from werkzeug import secure_filename
from urllib.parse import urljoin
from datetime import date, datetime, timedelta
import os, os.path, json

from firmware_server.klaytn import *
klay = Klaytn('http://ubuntu.hanukoon.com:8551/')

@app.route('/')
def home():
    today = date.today()
    log_data = {'labels': [], 'devices': [], 'firms': [], 'success': []}
    log_data['labels'] = list(reversed([(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(0, 7)]))
    for label in log_data['labels']:
        log_data['devices'].append(len(Log.query.filter_by(
            timestamp=label, 
            type='register'
        ).all()))
        log_data['firms'].append(len(Log.query.filter_by(
            timestamp=label,
            type='upload'
        ).all()))
        log_data['success'].append(len(Log.query.filter_by(
            timestamp=label,
            type='success'
        ).all()))
    return render_template('index.html', log_data=log_data)

@app.route('/register', methods=['GET', 'POST'])
def register():
    # name, wallet
    if request.method == 'POST':
        wallet = request.form.get('wallet')
        if len(wallet) != 42:
            return 'Not vaild wallet address'
        # try:
        newdevice = Device(
            name=request.form.get('name'),
            wallet=wallet,
            update=0
        )
        db.session.add(newdevice)
        db.session.commit()
        # except:
            # return 'Error'
        newlog = Log(
            type='register',
            timestamp=datetime.now().strftime('%Y-%m-%d'),
            json={
                'name':newdevice.name, 
                'wallet':newdevice.wallet, 
                'timestamp':datetime.now()
            }
        )
        db.session.add(newlog)
        db.session.commit()
        return 'Success<br>name: ' + newdevice.name + '<br>wallet: ' + newdevice.wallet
    return render_template('register.html')
    
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    # list of devices, file
    if request.method == 'POST':
        try:
            file = request.files['file']
        except:
            return json.dumps({'error': {'code': 400, 'message': 'No file'}}, sort_keys=True, indent=4)
        try:
            devices = [Device.query.filter_by(name=name).first() for name in request.form.getlist('devices')]
        except:
            return json.dumps({'error': {'code': 400, 'message': 'No devices specified'}}, sort_keys=True, indent=4)
        if file:
            # 파일경로와 랜덤키
            filename = secure_filename(file.filename)
            _dir = os.path.join(app.config['UPLOAD_FOLDER'], random_key() + hash_string(filename) + '/')
            print(app.config['UPLOAD_FOLDER'])
            print(_dir)
            if not os.path.exists(_dir):
                os.makedirs(_dir)
                print(_dir)
            _route = os.path.join(_dir + filename)
            print(_route)

            file.save(_route)
            newfile = File(
                route = _route,
                key = random_key(),
                hash = hash_file(_route)
            )
            db.session.add(newfile)
            db.session.commit()
            
            # logging
            newlog = Log(
                type='upload',
                timestamp=datetime.now().strftime('%Y-%m-%d'),
                json={
                    'route': newfile.route,
                    'hash': newfile.hash,
                    'timestamp':datetime.now()
                }
            )
            db.session.add(newlog)
            db.session.commit()

            # 트랜잭션 해시
            with open('./firmware_server/static/config.json') as f:
                json_data = json.loads(f.read())
                wallet = json_data['wallet']
                passphrase = json_data['passphrase']
            klay.unlockAccount(wallet, passphrase, 3000)
            print(wallet, newfile.key)
            _txhash = klay.sendData(wallet, newfile.key + '-' + newfile.hash)
            if not _txhash:
                return json.dumps({'error': {'code': 500, 'message': 'Error while sending'}}, sort_keys=True, indent=4)
            # save file in blockchain, get txHash
            newfile.txhash = _txhash
            db.session.commit() 

            for device in devices:
                device.update = newfile.id
            db.session.commit()             

            return json.dumps({'success': {'txhash': _txhash, 'file_id': newfile.id}}, sort_keys=True, indent=4)
        else:
            return json.dumps({'error': {'code': 400, 'message': 'No file'}}, sort_keys=True, indent=4)
    return render_template('upload.html', devices=Device.query.all())

@app.route('/download/<file_id>', methods=['POST'])
def download(file_id):
    try:
        file_id = int(file_id)
    except:
        return json.dumps({'error': {'code': 400, 'message': 'No '}}, sort_keys=True, indent=4)        
    # check if credentials are vaild
    key = request.json['key']
    thisfile = File.query.get(file_id)
    if key == thisfile.key:
        return json.dumps({'result': {
            'url': urljoin(
                request.url_root,
                thisfile.route.replace('firmware_server', '')
            )
        }}, sort_keys=True, indent=4)
    return json.dumps({'error': {'code': 401, 'message': 'Wrong login credentials'}}, sort_keys=True, indent=4)

@app.route('/check/update', methods=['POST'])
def check_update():
    device = Device.query.filter_by(wallet=request.form.get('wallet')).first()
    if device.update == 0: # nothing to update
        return json.dumps({'message': 'Nothing to update'}, sort_keys=True, indent=4)
    updated = File.query.get(device.update)
    return json.dumps({
        'message': 'Update available',
        'txHash': updated.txhash, 
        'file_id': updated.id
    }, sort_keys=True, indent=4)
    
@app.route('/check/hash/<file_id>', methods=['POST'])
def check_hash(file_id):
    file_id = int(file_id)
    thisfile = File.query.get(file_id)
    if thisfile.hash != request.form.get('hash'):
        return 'False'

    # log success
    newlog = Log(
        type='success',
        timestamp=datetime.now().strftime('%Y-%m-%d'),
        json={
            'route': thisfile.route,
            'hash': thisfile.hash,
            'timestamp':datetime.now()
        }
    )
    db.session.add(newlog)
    db.session.commit()

    device = Device.query.filter_by(wallet=request.form.get('wallet')).first()
    device.update = 0
    db.session.commit()

    return 'True'
    