from datetime import datetime
import os
import sqlite3
from flask import Flask, flash, request, Response, render_template, session, redirect, url_for
from jinja2 import Template, Environment, FileSystemLoader
from functools import wraps
import json
import urllib
import hashlib
import mysql.connector
import mysql.connector.pooling
import mysql.connector.errors
from mysql.connector import pooling
from mysql.connector import errorcode

app = Flask(__name__)

app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config.update(
    SESSION_COOKIE_SAMESITE='Lax'
)
app.secret_key = b'U\xfc\x92"DGw\xff\xcfG\x06\x90\xe7\x9d\x9d\xc7~\xee\xe3\xf1\xc2\xb8\xcb\xa5'

tiedosto = open("dbconfig.json", encoding="UTF-8")
dbconfig = json.load(tiedosto)

# luodaan mysql pooling
try:
    pool=mysql.connector.pooling.MySQLConnectionPool(pool_name="tietokantayhteydet",
    pool_size=2, #PythonAnywheren ilmaisen tunnuksen maksimi on kolme
    autocommit=True, #asettaa autocommitin päälle. 
    charset='utf8mb4',
    **dbconfig
    ) 

    print("Connection pool created successfully.")

except mysql.connector.Error as err:
  if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
    print("Tunnus tai salasana on väärin")
  elif err.errno == errorcode.ER_BAD_DB_ERROR:
    print("Tietokantaa ei löydy")
  else:
    print(err)

def admin_auth(f):
    ''' TÃ¤mÃ¤ decorator hoitaa kirjautumisen tarkistamisen ja ohjaa tarvittaessa kirjautumissivulle
    '''
    @wraps(f)
    def decorated(*args, **kwargs):
        # tÃ¤ssÃ¤ voisi olla monimutkaisempiakin tarkistuksia mutta yleensÃ¤ tÃ¤mÃ¤ riittÃ¤Ã¤        
        if not 'adminKirjautunut' in session:
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated

def auth(f):
    ''' TÃ¤mÃ¤ decorator hoitaa kirjautumisen tarkistamisen ja ohjaa tarvittaessa kirjautumissivulle
    '''
    @wraps(f)
    def decorated(*args, **kwargs):
        # tÃ¤ssÃ¤ voisi olla monimutkaisempiakin tarkistuksia mutta yleensÃ¤ tÃ¤mÃ¤ riittÃ¤Ã¤        
        if not 'kirjautunut' in session:
            return redirect(url_for('kirjaudu'))
        return f(*args, **kwargs)
    return decorated

@app.route("/", methods=["GET", "POST"])
@auth
def home():            
    return redirect(url_for('kirjaudu'))

@app.route('/admin',methods=['GET', 'POST'])
def admin(): 
    
    if request.method == "POST":
        tunnus = request.form.get("tunnus")
        salasana = request.form.get("salasana")   
        error_message = ""                 
            
        if not tunnus or not salasana:
            error_message = "Syötä tunnus ja salasana"
            return render_template("kirjauduAdmin.html", error_message=error_message)

        # salasanan hashaus
        avain = u"jokujokuavain"
        salasana = hashPassword(avain, salasana)    
        
        if tunnus == "admin" and salasana == '96d3cf4d4fe8e5ea39207038ce45a89a37b985c5f85dd4af9d68629c2895caaa947cab7bf9ba570883b14684476ed7d0208f6eaec079d34d1a486b672e472cc9':
            session['adminKirjautunut'] = "ok"
            return redirect(url_for('kilpailut'))
        else:
            error_message = "väärä tunnus tai salasana"
            return render_template("kirjauduAdmin.html", error_message=error_message)
            
    return render_template("kirjauduAdmin.html")

# NÄYTTÄÄ LISTAN KILPAILUISTA
@app.route('/kilpailut',methods=['GET', 'POST'])
@admin_auth
def kilpailut():     

    # jos käyttäjä painaa kisalinkkiä
    kisaid = request.args.get('kisaid')
    if kisaid:
        # jos käyttäjä valitsee toisen kilpailun, resetoidaan aiemmat sessiot sarjaid ja joukkueid
        if kisaid != session.get('kisaid'):
            session['sarjaid'] = None
            session['joukkueid'] = None
        session['kisaid'] = kisaid
        session['jasentenLukumaara'] = 5
        return redirect(url_for('kilpailu', kisaid=kisaid)) 
    
    try:
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan kilpailut ja vuosiluvut
        cur. execute("SELECT kisaid, nimi, DATE(alkuaika) AS alkuaika FROM kilpailut ORDER BY alkuaika ASC")
        kilpailut = cur.fetchall()    
        
        return render_template("adminKilpailut.html", kilpailut=kilpailut, sarjaid=session.get('sarjaid'), joukkueid=session.get('joukkueid'), kisaid=session.get('kisaid'))
    
    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()

# NÄYTTÄÄ LISTAN SARJOISTA
@app.route('/kilpailu/<int:kisaid>', methods=['GET', 'POST'])
@admin_auth
def kilpailu(kisaid):      

    # jos yritetään hypätä urlin kautta suoraan kilpailun sarjojen sivulle niin ohjataan pääsivulle
    if not session.get('kisaid'):
        return redirect(url_for('kilpailut'))
    
    # jos käyttäjä valitsi sarjan
    sarjaid = request.args.get('sarjaid')
    if sarjaid:
        session['sarjaid'] = sarjaid
        session['jasentenLukumaara'] = 5
        return redirect(url_for('sarja', sarjaid=sarjaid))     
    
    try:        
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan kilpailun nimi
        cur.execute("SELECT nimi FROM kilpailut WHERE kisaid = %s", (kisaid,))
        kilpailu = cur.fetchone()
        kilpailu_nimi = kilpailu['nimi'] if kilpailu else None
        session['kilpailuNimi'] = kilpailu_nimi

        # haetaan sarjat jotka kuuluvat kilpailuun
        cur.execute("""SELECT sarjaid, nimi FROM sarjat WHERE kilpailu = %s ORDER BY LOWER(nimi)""", (kisaid,))
        sarjat = cur.fetchall()

        return render_template("adminSarjat.html", sarjat=sarjat, sarjaid=session.get('sarjaid'), joukkueid=session.get('joukkueid'), kisaid=kisaid)
        
    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()


# NÄYTTÄÄ LISTAN RASTEISTA
@app.route('/rastit',methods=['GET', 'POST'])
@admin_auth
def rastit():         
    try:
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan kaikki kilpailun rastit ja niiden leimaukset yhdellä kyselyllä
        cur.execute("""
            SELECT rastit.koodi, rastit.id, rastit.lat, rastit.lon, rastit.kilpailu, COUNT(tupa.rasti) AS leimaukset_count
            FROM rastit
            LEFT OUTER JOIN tupa ON rastit.id = tupa.rasti
            WHERE rastit.kilpailu = %s
            GROUP BY rastit.id  
            ORDER BY leimaukset_count DESC
        """, (session.get('kisaid'),))
        
        # haetaan kaikki rastit ja leimaukset
        rasti_leimaukset = cur.fetchall()

        # näytetään lista eniten leimauksia saaneista rasteista
        return render_template('adminRastit.html', rastit=rasti_leimaukset)
    
    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()

            

# NÄYTTÄÄ LISTAN JOUKKUEISTA
@app.route('/sarja/<int:sarjaid>',  methods=['GET', 'POST'])
@admin_auth
def sarja(sarjaid):

    # jos yritetään hypätä urlin kautta suoraan sarjojen joukkueiden sivulle niin ohjataan edelliselle käydylle sivulle
    if not session.get('sarjaid'):        
        if session.get('kisaid'):
            return redirect(url_for('kilpailu', kisaid=session.get('kisaid')))
        else:
            return redirect(url_for('kilpailut'))

    # jos käyttäjä painoi joukkuelinkkiä joukkueiden seasta
    joukkueid = request.args.get('joukkueid')
    if joukkueid:
        session['joukkueid'] = joukkueid
        return redirect(url_for('joukkue', joukkueid=joukkueid)) 

    try:
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan sarjan nimi
        cur.execute("SELECT nimi FROM sarjat WHERE sarjaid = %s", (sarjaid,))
        sarja = cur.fetchone()
        sarja_nimi = sarja['nimi'] if sarja else None
        session['sarjaNimi'] = sarja_nimi

        # haetaan joukkueet jotka kuuluvat valittuun sarjaan
        cur.execute("""SELECT joukkueid, nimi FROM joukkueet WHERE sarja = %s""", (sarjaid,))
        joukkueet = cur.fetchall()

        jasentenLukumaara = session.get('jasentenLukumaara', 5) 
       
        if request.method == "POST":
            # jos jäseniä halutaan lisätä lisää
            if 'add_more' in request.form:
                jasentenLukumaara += 1
                session['jasentenLukumaara'] = jasentenLukumaara
                nimi = request.form.get('nimi', '')
                jasenet = request.form.getlist('jasenet[]')
                salasana=request.form.get('salasana', '')
                return render_template("adminSarjanJoukkueet.html", 
                                       joukkueet=joukkueet, 
                                       sarjaid=sarjaid, 
                                       joukkueid=session.get('joukkueid'), 
                                       kisaid=session.get('kisaid'), 
                                       jasentenLukumaara=jasentenLukumaara,
                                       nimi=nimi,
                                       salasana=salasana,
                                       jasenet=jasenet)
            # haetaan päivitetyt joukkueet, että nähdään uusi joukkue heti sivulla
            cur.execute("""SELECT joukkueid, nimi FROM joukkueet WHERE sarja = %s""", (sarjaid,))
            joukkueet = cur.fetchall() 
            
            result = handleJoukkueLisaaminen(con, cur)
            # jos tulee errorviesti, palautetaan sama sivu viestin kanssa
            if result["error_message"]:
                return render_template("adminSarjanJoukkueet.html", 
                    joukkueet=joukkueet, 
                    sarjaid=sarjaid, 
                    joukkueid=session.get('joukkueid'), 
                    kisaid=session.get('kisaid'),
                    error_message=result["error_message"], 
                    jasentenLukumaara=jasentenLukumaara
                )

            # haetaan päivitetyt joukkueet, että nähdään uusi joukkue heti sivulla
            cur.execute("""SELECT joukkueid, nimi FROM joukkueet WHERE sarja = %s""", (sarjaid,))
            joukkueet = cur.fetchall()   
  
        return render_template("adminSarjanJoukkueet.html", 
                               joukkueet=joukkueet, 
                               sarjaid=sarjaid, 
                               joukkueid=session.get('joukkueid'), 
                               kisaid=session.get('kisaid'), 
                               jasentenLukumaara=jasentenLukumaara
                            )
    
    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()


# NÄYTTÄÄ JOUKKUEEN
@app.route('/joukkue/<int:joukkueid>', methods=['GET', 'POST'])
@admin_auth
def joukkue(joukkueid):

    # jos joukkueid:tä ei ole sessiossa, tarkistetaan onko sarjaid. muuten mennään takaisin pääsivulle
    if not session.get('joukkueid'):
        if session.get('sarjaid'):
            return redirect(url_for('sarja', sarjaid=session.get('sarjaid')))
        elif session.get('kisaid'):
            return redirect(url_for('kilpailu', kisaid=session.get('kisaid')))
        else:
            return redirect(url_for('kilpailut')) 
    
    session['joukkueid'] = joukkueid
    
    try: 
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan joukkue joilla tietty joukkueid
        cur.execute("""SELECT * FROM joukkueet WHERE joukkueid = %s""", (joukkueid,))
        joukkue = cur.fetchone()      

        if joukkue:
            jasenet = json.loads(joukkue['jasenet'])
            session['joukkueNimi'] = joukkue['nimi']
        else:
            jasenet = []

        # Haetaan sarja johon tämä joukkue kuuluu
        sarja_id = joukkue['sarja'] if joukkue else None

        # Haetaan kilpailu johon tämä sarja kuuluu
        cur.execute("""SELECT kilpailu FROM sarjat WHERE sarjaid = %s""", (sarja_id,))
        kilpailu_id = cur.fetchone()['kilpailu'] if sarja_id else None

        # Haetaan kaikki sarjat jotka kuuluvat tähän kilpailuun
        cur.execute("""SELECT * FROM sarjat WHERE kilpailu = %s""", (kilpailu_id,))
        sarjat = cur.fetchall()     

        # POST pyyntö
        if request.method == "POST":
            if 'delete_joukkue' in request.form:
                result = handleJoukkueenPoistaminen(con, cur)

                # jos tulee errorviesti, palautetaan sama sivu viestin kanssa
                if result["error_message"]:
                        return render_template(
                            "adminJoukkueTiedot.html", joukkue=joukkue, sarjat=sarjat, jasenet=jasenet, error_message=result["error_message"])
                # palataan sarjan joukkueet -sivulle jos ei erroreita
                return redirect(url_for('sarja', sarjaid=session.get('sarjaid')))
            
            else:
                # Päivitetään joukkueen tiedot käyttämällä handleJoukkueUpdate funktiota
                result = handleJoukkueUpdate(request, con, cur, joukkueid)

                # Tarkistetaan, onko virheilmoitus
                if result["error_message"]:
                    return render_template(
                        "adminJoukkueTiedot.html", joukkue=joukkue, sarjat=sarjat, jasenet=jasenet, error_message=result["error_message"])

                # haetaan päivitetyt tiedot tallennuksen jälkeen
                cur.execute("""SELECT * FROM joukkueet WHERE joukkueid = %s""", (joukkueid,))
                joukkue = cur.fetchone()
                jasenet = json.loads(joukkue['jasenet']) if joukkue['jasenet'] else []

                # Päivitetty onnistuneesti, palataan takaisin joukkueen tietoihin
                return render_template(
                    "adminJoukkueTiedot.html", joukkue=joukkue, sarjat=sarjat, jasenet=jasenet)       
        
        # renderöidään näkymä GET pyynnölle
        return render_template(
            "adminJoukkueTiedot.html", joukkue=joukkue, sarjat=sarjat, jasenet=jasenet)

    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()


# apufunktio salasanan suojaamiseen
def hashPassword(joukkueid, salasana):
    m = hashlib.sha512()
    m.update(str(joukkueid).encode("UTF-8"))
    m.update(salasana.encode("UTF-8"))
    return m.hexdigest()


# joukkueen tietojen muokkaus ja tallennus 
def handleJoukkueUpdate(request, con, cur, joukkueid):
   
    joukkueenNimi = request.form.get("nimi", "").strip()
    salasana = request.form.get("salasana", "").strip()
    sarja = request.form.get("sarja")
    jasenet = [jasen.strip() for jasen in request.form.getlist('jasenet[]') if jasen.strip()]

    # varmistetaan että joukkueen nimi on syötetty
    if not joukkueenNimi:
        return {"error_message": "Joukkueen nimi ei saa olla tyhjä!"}
    
    # jäseniä tulee olla vähintään kaksi
    if len(jasenet) < 2:
        return {"error_message": "Joukkueessa tulee olla vähintään 2 jäsentä"}

    # jäsenillä on ainutlaatuiset nimet
    if len(jasenet) != len(set(map(str.lower, jasenet))):
        return {"error_message": "Jäsenet eivät saa olla saman nimisiä!"}

    # joukkueen nimi on ainutlaatuinen
    cur.execute("""
        SELECT nimi 
        FROM joukkueet 
        WHERE LOWER(nimi) = LOWER(%s) AND sarja = %s AND joukkueid != %s
    """, (joukkueenNimi, sarja, joukkueid))

    result = cur.fetchone()
    if result:
        return {"error_message": "Joukkueen nimi on jo käytössä kilpailussa"}
    
    # serialisoidaan jäsenet
    jasenet_json = json.dumps(jasenet)
    try:
        if salasana:
            print(f"Updating password for team {joukkueenNimi}: {salasana}")  # Debug print
            hashUusiSalasana = hashPassword(joukkueid, salasana)
            print(f'päivitetty salasana: {hashUusiSalasana}')
            # jos salasana on annettu, päivitetään salasana, muuten ei
            cur.execute(
                """
                UPDATE joukkueet
                SET nimi = %s, salasana = %s, sarja = %s, jasenet = %s
                WHERE joukkueid = %s
                """,
                (joukkueenNimi, hashUusiSalasana, sarja, jasenet_json, joukkueid),
            )

        else:
            print(f"No password change. Keeping old password for team {joukkueenNimi}")  # Debug print
            # jos salasanaa ei ole annettu, niin ei päivitetä sitä
            cur.execute(
                """
                UPDATE joukkueet
                SET nimi = %s, sarja = %s, jasenet = %s
                WHERE joukkueid = %s
                """,
                (joukkueenNimi, sarja, jasenet_json, joukkueid),
            )

        # tallennetaan muutokset tietokantaan
        con.commit()
        
        # jos erroria ei tule, tyhjä palautetaan
        return {"error_message": ""}
    except:
        return {"error_message": "Joukkueen nimi on jo käytössä."}
    

# joukkueen lisääminen
def handleJoukkueLisaaminen(con, cur):
    nimi1 = request.form.get("nimi")
    salasana = request.form.get("salasana", "").strip()
    sarja = session.get('sarjaid')
    jasenet = [jasen.strip() for jasen in request.form.getlist('jasenet[]') if jasen.strip()]
    joukkueid = session.get('joukkueid')
    kisaid = session.get('kisaid')
    
    # varmistetaan että joukkueen nimi on syötetty
    if not nimi1:
        return {"error_message": "Joukkueen nimi ei saa olla tyhjä!"}

    # varmistetaan että joukkueen salasana on syötetty
    if not salasana:
        return {"error_message": "Joukkueen salasana ei saa olla tyhjä!"}
    
    # jäseniä tulee olla vähintään kaksi
    if len(jasenet) < 2:
        return {"error_message": "Joukkueessa tulee olla vähintään 2 jäsentä"}

    # jäsenillä on ainutlaatuiset nimet
    if len(jasenet) != len(set(map(str.lower, jasenet))):
        return {"error_message": "Jäsenet eivät saa olla saman nimisiä!"}

    cur.execute("""SELECT sarjaid FROM sarjat WHERE kilpailu = %s""", (kisaid,))
    sarjaIds = cur.fetchall() 
    print(f'1{sarjaIds}')
    sarjaIds = [sarja['sarjaid'] for sarja in sarjaIds]
    print(f'2{sarjaIds}')
    
    # joukkueen nimi on ainutlaatuinen
    for sarjaid in sarjaIds:
        cur.execute("""
            SELECT nimi 
            FROM joukkueet 
            WHERE LOWER(nimi) = LOWER(%s) 
            AND sarja = %s
            """, (nimi1, sarjaid))
        
        result = cur.fetchone()
        print(f'result was found {result}')

        if result:
            return {"error_message": "Joukkueen nimi on jo käytössä kilpailussa"}
    

    # muutetaan jäsenet jsoniin
    jasenet_json = json.dumps(jasenet)

    # hashataan salasana
    hashedSalasana = hashPassword(joukkueid, salasana)
    try:
        print(f"Preparing to insert: nimi={nimi1}, hashedSalasana={hashedSalasana}, jasenet_json={jasenet_json}, sarja={sarja}")

        # alustetaan joukkueen lisääminen halutuilla tiedoilla
        cur.execute("""INSERT INTO joukkueet (nimi, salasana, jasenet, sarja) 
                    VALUES (%s, %s, %s, %s)""", (nimi1, hashedSalasana, jasenet_json, sarja))
        
        #select * from joukkueet where nimi=nimi1
        
        con.commit()   
        session['jasentenLukumaara'] = 5
        print(f'ei päässyt tänne')

    # jos erroria ei tule, tyhjä palautetaan
        return {"error_message": ""}
    except Exception as e:
        print(f"Error during insertion: {e}")
        return {"error_message": "Joukkueen nimi on jo käytössä toisessa kilpailussa."}



# joukkueen poistava funktio
def handleJoukkueenPoistaminen(con, cur):    
    joukkueid = session.get('joukkueid')

    try:        

        # haetaan ne rastit, jotka kuuluvat tupaan jotka kuuluvat joukkueeseen
        cur.execute("""SELECT rastit.* FROM rastit JOIN tupa ON tupa.rasti = rastit.id WHERE tupa.joukkue = %s""", (joukkueid,))
        rasti = cur.fetchall()
        print(f'rastit{rasti}')

        # jos joukkueella on rasteja, palautetaan vain error viesti eikä suoriteta joukkueen poistoa loppuun
        if rasti:
            return {"error_message": "Ei voi poistaa, joukkueella on rastileimauksia"}
        
        # alustetaan joukkueen poisto
        cur.execute("""DELETE FROM joukkueet WHERE joukkueid = %s""", (joukkueid,))
        con.commit()           

        # poistetaan poistetun joukkuen id sessiosta
        session['joukkueid'] = None  

    # jos erroria ei tule, tyhjä palautetaan
        return {"error_message": ""}
    except:
        return {"error_message": "Joukkueen poisto epäonnistui."}

            


@app.route('/kirjaudu',methods=['GET', 'POST'])
def kirjaudu():    

    try:
        
        # luodaan yhteys tietokantaan
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan kilpailut ja vuosiluvut
        cur.execute("SELECT kisaid, nimi, alkuaika FROM kilpailut")
        kilpailut = cur.fetchall()
        kilpailutjaVuosi = []

        # haetaan vuosiluku
        for kilpailu in kilpailut:
            alkuaika = kilpailu["alkuaika"]
            if alkuaika:
                # muunnetaan alkuaika datetime-objektiksi
                vuosi = alkuaika.year
            else:
                vuosi = None 

            # Lisätään uusi kilpailu, joka sisältää myös vuosiluvun
            kilpailutjaVuosi.append({
                'kisaid': kilpailu['kisaid'],
                'nimi': kilpailu['nimi'],
                'vuosi': vuosi
            })
        
        # kilpailut aakkosjärjestykseen
        kilpailutjaVuosi = sorted(kilpailutjaVuosi, key=lambda k: k['nimi'])
    
        if request.method == "POST":            

            # haetaan lomakkeesta syötetyt tiedot
            tunnus = request.form.get("tunnus")
            salasana = request.form.get("salasana")    
            print(f'syötetty salasana: {salasana}')        
            valittuKilpailuId = request.form.get("kilpailu") 

            if not tunnus or not salasana or not valittuKilpailuId:
                error_message = "valitse kilpailu ja syötä tunnus sekä salasana"
                return render_template("kirjaudu.html", kilpailut=kilpailutjaVuosi, error_message=error_message)
            
            # haetaan joukkueenId ja salattu salasana tunnuksen mukaan
            cur.execute("""SELECT nimi, joukkueid, salasana FROM joukkueet WHERE nimi = %s""", (tunnus,))
            joukkueidJaSalasana = cur.fetchone()
            print(f'joukkue ja salasana: {joukkueidJaSalasana}')

            # jos käyttäjätunnus on väärin
            if not joukkueidJaSalasana:
                error_message = "Kirjautuminen epäonnistui"
                return render_template("kirjaudu.html", kilpailut=kilpailutjaVuosi, error_message=error_message)

            joukkueid = joukkueidJaSalasana['joukkueid']
            storedHadhedPassword = joukkueidJaSalasana['salasana']
            print(f'databasessa ollut salasana: {storedHadhedPassword}')

            # hashataan salasana ja vertaillaan joukkueid:n mukaan
            hashedInputPassword = hashPassword(joukkueid, salasana)
            print(f'syötetty salasana hashattuna: {hashedInputPassword}')

            # haetaan sarjat
            cur.execute("""SELECT sarjaid FROM sarjat WHERE kilpailu = %s""", (valittuKilpailuId,))
            sarjat = cur.fetchall()

            # tarkistetaan onko joukkuenimi olemassa sarjassa joka on valitussa kilpailussa
            team_exists = False
            for sarja in sarjat:
                sarja_id = sarja["sarjaid"]

                # haetaan joukkue 
                cur.execute("""SELECT nimi FROM joukkueet WHERE sarja = %s AND nimi = %s""", (sarja_id, tunnus))
                joukkue = cur.fetchone()

                if joukkue:
                    team_exists = True
                    break
        
            if team_exists and hashedInputPassword == storedHadhedPassword:
                # jos kaikki ok niin asetetaan sessioon tieto kirjautumisesta ja ohjataan laskurisivulle
                session['kirjautunut'] = "ok"
                session['valittuKilpailuId'] = valittuKilpailuId

                cur.execute("""SELECT joukkueid, nimi FROM joukkueet WHERE sarja = %s AND nimi = %s""", (sarja_id, tunnus))
                joukkue = cur.fetchone()
                
                if joukkue:
                    session['joukkueid'] = joukkue['joukkueid']  # Tallennetaan joukkueen ID
                    session['käyttäjä'] = joukkue['nimi'] 

                # haetaan kilpailun nimi ja päivämäärä tietokannasta
                cur.execute("SELECT nimi, alkuaika, kisaid FROM kilpailut WHERE kisaid = %s", (valittuKilpailuId,))
                kilpailu = cur.fetchone()
                if kilpailu:
                    session['kilpailu_nimi'] = kilpailu['nimi']
                    session['kilpailu_pvm'] = kilpailu['alkuaika']

                # salasanan ja tunnuksen ollessa oikein ohjataan pääsivulle
                return redirect(url_for('joukkueet'))
            
            else:
                error_message = "Kirjautuminen epäonnistui: virheellinen salasana"
                return render_template("kirjaudu.html", kilpailut=kilpailutjaVuosi, error_message=error_message)

        # GET pyynnössä renderöidään kirjaudu sivu
        return render_template("kirjaudu.html", kilpailut=kilpailutjaVuosi)
    
    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()



@app.route('/logout', methods=['POST'])
def logout():    
    isAdmin = session.get('adminKirjautunut')
    session.clear()
    
    if isAdmin == "ok":
        return redirect(url_for('admin'))
    else:
        return redirect(url_for('kirjaudu'))


@app.route('/joukkueet')
@auth
def joukkueet():
    try:
        kisaId = session.get('valittuKilpailuId')  
        käyttäjä = session.get('käyttäjä')      

        # luodaan yhteys tietokantaan
        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # haetaan kilpailuun liittyvät sarjat aakkosjärjestyksessä
        cur.execute('SELECT * FROM sarjat WHERE kilpailu = %s ORDER BY LOWER(nimi)', (kisaId,))
        sarjat = cur.fetchall()  # Haetaan sarjat kilpailusta       

        # haetaan kaikki joukkueet aakkosjärjestyksessä 
        cur.execute('SELECT * FROM joukkueet ORDER BY LOWER(nimi)')        
        joukkueet = cur.fetchall()
        
        joukkueetSarjassa = []
        for sarja in sarjat:
            for joukkue in joukkueet:
                if joukkue['sarja'] == sarja['sarjaid']:
                    joukkueetSarjassa.append(joukkue)

        jasenet = {}
        for joukkue in joukkueet:
            cur.execute('SELECT jasenet FROM joukkueet WHERE joukkueid = %s', (joukkue['joukkueid'],))
            jasenetData = cur.fetchone()
            if jasenetData:
                jasenet[joukkue['joukkueid']] = json.loads(jasenetData['jasenet'])        

        # päivämäärä ilman kellonakaa ylävalikkoa varten
        pvmIlmanAikaa = session.get('kilpailu_pvm').strftime('%Y-%m-%d')

        kilpailu = {
            'nimi': session.get('kilpailu_nimi'),
            'pvm': pvmIlmanAikaa
        }          
        
        return render_template('joukkueet.html', sarjat=sarjat, joukkueet=joukkueet, jasenet=jasenet, kilpailu=kilpailu, käyttäjä=käyttäjä)

    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {str(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()


@app.route('/tiedot', methods=['GET', 'POST'])
@auth
def tiedot():
    try:
        # Haetaan kilpailun tiedot sessiosta
        joukkueid = session.get('joukkueid')
        kilpailu_nimi = session.get('kilpailu_nimi')
        kilpailu_pvm = session.get('kilpailu_pvm').strftime('%Y-%m-%d')
        kilpailuid = session.get('valittuKilpailuId')

        con = pool.get_connection()
        cur = con.cursor(dictionary = True)

        # Haetaan joukkueen tiedot
        cur.execute("""
            SELECT nimi, salasana, sarja, jasenet
            FROM joukkueet
            WHERE joukkueid = %s
        """, (joukkueid,))
        joukkue = cur.fetchone()

        # Muunnetaan jäsenet listaksi
        jasenet_list = json.loads(joukkue['jasenet']) if joukkue['jasenet'] else []

        # Haetaan sarjat kilpailusta
        cur.execute('SELECT * FROM sarjat WHERE kilpailu = %s', (kilpailuid,))
        sarjat = cur.fetchall()

        # Handle POST requests
        if request.method == "POST":
            result = handleJoukkueUpdate(request, con, cur, joukkueid)
            # jos tulee errorviesti, palautetaan sama sivu viestin kanssa
            if result["error_message"]:
                return render_template(
                    "joukkuetiedot.html",
                    kilpailu_nimi=kilpailu_nimi,
                    joukkue=joukkue,
                    sarjat=sarjat,
                    jasenet=jasenet_list,
                    kilpailu_pvm=kilpailu_pvm,
                    error_message=result["error_message"],
                )

            # jos päivitys on onnistunut niin ohjataan joukkueet sivulle
            return redirect(url_for("joukkueet"))

        # renderöidään joukkuetiedot sivu
        return render_template(
            "joukkuetiedot.html",
            kilpailu_nimi=kilpailu_nimi,
            kilpailu_pvm=kilpailu_pvm,
            joukkue=joukkue,
            sarjat=sarjat,
            jasenet=jasenet_list,
        )

    except mysql.connector.Error as e:
        return Response(f"Tietokanta ei aukene: {str(e)}", status=500)
    except Exception as e:
        return Response(f"Tapahtui virhe: {repr(e)}", status=500)

    finally:
        if con.is_connected():
            cur.close()
            con.close()
   
if __name__ == '__main__':
    app.run(debug=True)