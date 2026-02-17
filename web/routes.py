# -*- coding: utf-8 -*-
"""web/routes.py - Main page routes blueprint."""

from flask import Blueprint, redirect, render_template, session, url_for

from web.auth import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    if session.get("role") == "gestor":
        return redirect(url_for("main.gestor_dashboard"))
    return redirect(url_for("main.dashboard"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "gestor":
        return redirect(url_for("main.gestor_dashboard"))
    return render_template("dashboard.html")


@main_bp.route("/client/<path:nome>")
@login_required
def client_detail(nome: str):
    return render_template("client_detail.html", client_name=nome)


@main_bp.route("/gestor")
@login_required
def gestor_dashboard():
    return render_template("gestor_dashboard.html")


@main_bp.route("/gestor/clientes")
@login_required
def gestor_clientes():
    return render_template("gestor_clientes.html")


@main_bp.route("/history")
@login_required
def history():
    if session.get("role") == "gestor":
        return redirect(url_for("main.gestor_dashboard"))
    return render_template("history.html")


@main_bp.route("/logs")
@login_required
def logs():
    if session.get("role") == "gestor":
        return redirect(url_for("main.gestor_dashboard"))
    return render_template("logs.html")
