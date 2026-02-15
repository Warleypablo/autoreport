# -*- coding: utf-8 -*-
"""web/routes.py - Main page routes blueprint."""

from flask import Blueprint, redirect, render_template, url_for

from web.auth import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    return redirect(url_for("main.dashboard"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@main_bp.route("/client/<path:nome>")
@login_required
def client_detail(nome: str):
    return render_template("client_detail.html", client_name=nome)


@main_bp.route("/history")
@login_required
def history():
    return render_template("history.html")


@main_bp.route("/logs")
@login_required
def logs():
    return render_template("logs.html")
